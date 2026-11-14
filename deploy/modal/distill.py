"""N+1 training on Modal: LoRA-tune Qwen3-30B-A3B-Instruct-2507 on 763B-verified code solutions, then eval base vs tuned.

Not a served tier. Nothing here stays up: every function ends when it returns (no web endpoint, min_containers=0,
scaledown_window=60 s). Data goes in and results come out through the `chimera-distill` Volume.

  modal volume put chimera-distill bench/.scratch/distill/train.jsonl /in/train.jsonl
  modal volume put chimera-distill bench/.scratch/distill/heldout_prompts.jsonl /in/heldout_prompts.jsonl
  modal run deploy/modal/distill.py::download          # CPU only, no GPU bill
  modal run deploy/modal/distill.py::train             # H200: LoRA, then merged copy
  modal run deploy/modal/distill.py::evaluate --which base   (and --which tuned)
  modal app list                                       # must show nothing of ours running

The base is the HF checkpoint of the same family as the Akash `qwen3:30b-instruct` (Qwen3-30B-A3B-Instruct-2507).
LoRA touches the attention projections only: the MoE experts are fused tensors that peft cannot wrap cleanly.
"""
import json
import time

import modal

BASE = "Qwen/Qwen3-30B-A3B-Instruct-2507"
VOL_PATH = "/vol"
MINUTES = 60

app = modal.App("chimera-distill")
vol = modal.Volume.from_name("chimera-distill", create_if_missing=True)

train_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("torch==2.8.0", "transformers==4.57.1", "peft==0.17.1", "accelerate==1.10.1",
                 "huggingface_hub[hf_transfer]", "safetensors")
    .env({"HF_HOME": f"{VOL_PATH}/hf", "HF_HUB_ENABLE_HF_TRANSFER": "1"})
)
vllm_image = (
    modal.Image.from_registry("vllm/vllm-openai:v0.33.0")
    .entrypoint([])
    .run_commands("ln -sf $(command -v python3) /usr/local/bin/python")
    .env({"HF_HOME": f"{VOL_PATH}/hf", "VLLM_CACHE_ROOT": f"{VOL_PATH}/vllm-cache"})
)


@app.function(image=train_image, volumes={VOL_PATH: vol}, timeout=60 * MINUTES)
def download() -> str:
    from huggingface_hub import snapshot_download

    p = snapshot_download(BASE)
    vol.commit()
    return p


@app.function(image=train_image, gpu="H200", volumes={VOL_PATH: vol}, timeout=180 * MINUTES, scaledown_window=60)
def train(epochs: int = 2, lr: float = 1e-4, rank: int = 16, max_len: int = 1024) -> dict:
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments

    t0 = time.time()
    tok = AutoTokenizer.from_pretrained(BASE)
    rows = [json.loads(x) for x in open(f"{VOL_PATH}/in/train.jsonl") if x.strip()]

    def encode(r):  # loss on the answer tokens only
        p = tok.apply_chat_template([{"role": "user", "content": r["prompt"]}], tokenize=False, add_generation_prompt=True)
        pi = tok(p, add_special_tokens=False)["input_ids"]
        ai = tok(r["response"] + "<|im_end|>", add_special_tokens=False)["input_ids"]
        ids = (pi + ai)[:max_len]
        return {"input_ids": ids, "labels": ([-100] * len(pi) + ai)[:max_len]}

    data = [encode(r) for r in rows]

    def collate(b):
        n = max(len(x["input_ids"]) for x in b)
        pad = tok.pad_token_id
        return {"input_ids": torch.tensor([x["input_ids"] + [pad] * (n - len(x["input_ids"])) for x in b]),
                "attention_mask": torch.tensor([[1] * len(x["input_ids"]) + [0] * (n - len(x["input_ids"])) for x in b]),
                "labels": torch.tensor([x["labels"] + [-100] * (n - len(x["labels"])) for x in b])}

    model = AutoModelForCausalLM.from_pretrained(BASE, torch_dtype=torch.bfloat16, device_map={"": 0})
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    model = get_peft_model(model, LoraConfig(r=rank, lora_alpha=2 * rank, lora_dropout=0.05, task_type="CAUSAL_LM",
                                             target_modules=["q_proj", "k_proj", "v_proj", "o_proj"]))
    model.print_trainable_parameters()
    args = TrainingArguments(output_dir=f"{VOL_PATH}/out/ckpt", per_device_train_batch_size=4, gradient_accumulation_steps=4,
                             num_train_epochs=epochs, learning_rate=lr, lr_scheduler_type="cosine", warmup_ratio=0.05,
                             bf16=True, logging_steps=5, save_strategy="no", report_to=[], group_by_length=True,
                             remove_unused_columns=False, dataloader_num_workers=0)
    tr = Trainer(model=model, args=args, train_dataset=data, data_collator=collate)
    res = tr.train()
    model.save_pretrained(f"{VOL_PATH}/out/adapter")
    t_train = time.time() - t0
    merged = model.merge_and_unload()
    merged.save_pretrained(f"{VOL_PATH}/out/merged", safe_serialization=True)
    tok.save_pretrained(f"{VOL_PATH}/out/merged")
    vol.commit()
    return {"rows": len(rows), "epochs": epochs, "train_loss": res.training_loss, "steps": res.global_step,
            "train_seconds": round(t_train), "total_seconds": round(time.time() - t0),
            "log": [h for h in tr.state.log_history if "loss" in h][::4]}


@app.function(image=vllm_image, gpu="H200", volumes={VOL_PATH: vol}, timeout=60 * MINUTES, scaledown_window=60)
def evaluate(which: str) -> dict:
    """Offline vLLM batch, temperature 0, same prompts for base and tuned. Writes /out/gen_<which>.jsonl."""
    from vllm import LLM, SamplingParams

    path = BASE if which == "base" else f"{VOL_PATH}/out/merged"
    rows = [json.loads(x) for x in open(f"{VOL_PATH}/in/heldout_prompts.jsonl") if x.strip()]
    t0 = time.time()
    llm = LLM(model=path, tokenizer=BASE, dtype="bfloat16", max_model_len=6144, gpu_memory_utilization=0.9,
              enable_prefix_caching=True)
    t_load = time.time() - t0
    sp = SamplingParams(temperature=0.0, max_tokens=1500)
    t1 = time.time()
    outs = llm.chat([[{"role": "user", "content": r["prompt"]}] for r in rows], sp)
    t_gen = time.time() - t1
    with open(f"{VOL_PATH}/out/gen_{which}.jsonl", "w") as f:
        for r, o in zip(rows, outs):
            f.write(json.dumps({"id": r["id"], "text": o.outputs[0].text, "tokens_out": len(o.outputs[0].token_ids),
                                "tokens_in": len(o.prompt_token_ids)}) + "\n")
    vol.commit()
    return {"which": which, "n": len(rows), "load_s": round(t_load), "gen_s": round(t_gen)}
