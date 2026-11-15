# CHIMERA: how the ladder and speculative decoding fit, what we measured, what to change next

DRAFT. Status: the Modal speculative-decoding runs (section 4) have **not** started; they wait for the user's go. The scripts are written and tested offline on fake servers (`tests/test_spec_modal.py`). Sections 1, 2, 3, 5, 6, 7 are written from earlier reports. Cells marked PENDING are filled from `bench/results_spec_modal.md` after the runs.

## 1. How the pieces fit today

Two different mechanisms live in the repo. They answer different questions.

| Mechanism | Question it answers | Where | Status |
|---|---|---|---|
| Ladder (cascade) | Which model should answer this whole prompt? | `router.py`, `ladder.py`, `tiers.py` | In the product path |
| Speculative decoding | Can a small model write the tokens and a big one only check them? | `bench/verify_server.py`, `inference/specplus.py` | Bench only, not in the product path |

```
prompt
  |
  v
[Tier 0  Supabase cache]  exact hash, then cosine >= 0.97 ----hit----> answer ($0, ~120 ms)
  | miss
  v
[Tier 1  GPU 30B, Ollama]  confidence >= 0.95? ----yes----> answer
  | no / failed check
  v
[Tier 2  Modal 120B]  (optional, off)
  |
  v
[Tier 3  Crusoe 763B]  ----> answer ----> tests pass? ----> Supabase teacher_pairs + Aura graph
```

Speculative decoding sits **inside** one tier call, not between tiers:

```
small model (drafter)  --K token ids-->  big model (verifier, one forward pass)
        ^                                        |
        +------ accepted count m + next token ---+      output == big model alone (greedy)
```

Why it is not in the ladder: the 763B on Crusoe rejects `echo`, so it cannot score draft tokens, and Ollama returns no prompt logprobs. Only vLLM or llama.cpp servers can verify (`docs/architecture.md`).

## 2. Measured results so far (single runs, from the earlier reports)

| Report | What it showed | Verdict |
|---|---|---|
| `bench/spec_results.md` | Mac 3B drafts, V100 30B verifies over the internet. Round trip about 0.6 s, alpha 0.68 at K=4 and 0.52 at K=8. 2.1 and 3.3 tok/s vs 14.6 tok/s plain Ollama. | 4.5x to 7x slower |
| `bench/results_specplus.md` | Spec+ (adaptive K, tree, pipelining, free drafts, compact wire) vs plain spec, stand-in target. | 1.14x to 1.22x over plain spec, still below the big model alone |
| `bench/results_suite.md` | 300 real prompts, 763B only vs the pool. | see file; losses listed next to wins |
| `bench/results_cost_case.md` | 301 coding tasks. V100 Qwen3-30B passes 98% of trivial, 78% of hard; 763B 100% and 92%. | A 30B does trivial code; hard code needs the top |
| `bench/results_backend.md` | 60 prompts through the real ladder. 45/48 correct on both BASE and COLD. | Cache is the big win on repeats |
| `bench/results_replay.md` | 300 real oasst1 requests. 30B answered 6%; 9.8% more 763B tokens; ladder p50 82.7 s vs 10.6 s. | Ladder does not cut tokens on open chat, and is 8x slower |
| `bench/results_bank.md` | Solved-problem bank: 93.8% served on the same problems, 30.0% on reworded ones, 0 wrong hits caught by tests. | Works for repeats |
| `bench/results_memory.md` | N+1 memory: 30B 85.0% alone, 87.5% with memory, 87.5% with 3 random examples. | Not distinguishable from noise |
| `bench/results_distill.md` | LoRA on 763B answers: 92.2% to 88.3% on 566 held-out. | Made it worse |
| `bench/results_modal.md` | gpt-oss-120b on an H200 vs 763B: $0.11 of H200 time vs $0.0058 of tokens; 1,352 ms vs 728 ms. | 763B alone wins |

## 3. Where time and money go

| Cost | Evidence | Reading |
|---|---|---|
| Time: failed 30B call, then 763B | replay: ladder p50 82.7 s vs 10.6 s; ladder p90 in backend 91.6 s | The shared GPU box and the climb dominate latency |
| Time: network round trip per spec round | spec_results: about 0.6 s | A round trip costs more than 8 big-model tokens |
| Money: idle GPU | modal results: H200 about $4.5 per hour | Pays only when kept busy |
| Money: 763B tokens | $0.29/M in, $1.20/M out | So cheap that cheap tiers save little |
| Money: Modal runs of this task | PENDING | |

## 4. This run: Modal L40S draft + H200 verify (PENDING)

Plan, fixed before any run (`deploy/modal/spec_modal.py`, `bench/run_spec_modal.py`, loop in `bench/spec_modal_core.py`):

- **Prompts:** 48 measured (28 code from `bench/cost_case/tasks.jsonl` and HumanEval/MBPP, 10 Dolly chat, 5 GSM8K, 5 MMLU short answers) plus 2 warm-up prompts that are not measured.
- **Fairness:** temperature 0, max_tokens 256 everywhere, `--generation-config vllm` so no repo sampling default (the 480B ships `repetition_penalty 1.05`) changes greedy output. Every run starts every prompt with a cold prefix cache (a cache salt per run and prompt); a spec run reuses only its own earlier rounds. Cold starts are logged apart from the runs.
- **Lossless check:** every spec run is compared token by token with the 235B alone on all 48 prompts; the big model alone is also run twice. At each first difference the 235B's top-2 logprob gap is read, to tell a GPU near-tie from a bug.
- **Network:** the drafter box calls the 235B box through Modal's public HTTPS endpoint, so each verify is a real round trip. Network time = round trip minus the server's own time.
- **Modal off when idle:** each job is one ephemeral `modal run`; GPU boxes scale down after 2 idle minutes; the driver stops any leftover by App ID and saves `modal app list` after every job.

Models. All are Qwen3 and share one `tokenizer.json` (same SHA-256 from 0.6B to 480B, read from the Hugging Face API):

| Role | Model | Box |
|---|---|---|
| small | Qwen3-4B-Instruct-2507-FP8 | 1 L40S |
| mid ("local machine") | Qwen3-30B-A3B-Instruct-2507-FP8 | 1 L40S |
| big ("server") | Qwen3-235B-A22B-Instruct-2507-FP8 | 2 H200 |
| biggest Qwen3 | Qwen3-Coder-480B-A35B-Instruct-FP8 | 4 H200 |
| same-box heads | RedHatAI EAGLE-3 speculators for the 235B and the 30B | inside each vLLM |

| Run | Draft | Verify | tok/s | alpha | RTT p50 | lossless |
|---|---|---|---|---|---|---|
| 30B alone | 30B L40S | none | PENDING | | | |
| 235B alone | none | 235B | PENDING | | | |
| plain spec K=4, K=8 | 30B | 235B across the network | PENDING | | | |
| Spec+ (adaptive K, pipelined drafts, free prompt-copy drafts) | 30B | 235B | PENDING | | | |
| 4B -> 235B | 4B L40S | 235B | PENDING | | | |
| chain 4B -> 30B -> 235B | 4B inside the 30B's vLLM | 235B | PENDING | | | |
| same box: EAGLE-3, n-gram, 4B draft model, suffix | inside the 235B's vLLM | | PENDING | | | |
| 30B -> 480B | 30B L40S | Coder-480B | PENDING | | | |

**No 700B+ same-family model.** Qwen3's largest open model is the Coder-480B-A35B. Qwen3.5 (4B, 35B-A3B, 122B-A10B, 397B-A17B) is a separate tokenizer (248,320 tokens vs 151,936), so it cannot verify Qwen3 drafts; it tops out at 397B. Qwen3-Max is API-only. DeepSeek 763B on Crusoe has a different tokenizer and rejects `echo`, so it cannot score drafts.

## 5. Ranked improvements

Gain is expected, not measured, unless a file is named.

| # | Change | Expected gain | Effort | Risk | Evidence |
|---|---|---|---|---|---|
| 1 | Put the drafter and the verifier on one box (vLLM built-in draft model, n-gram or EAGLE-3 head) instead of across the internet | Removes the 0.6 s round trip; papers report 2x to 3x on code | Low (a vLLM flag) | Low | Leviathan et al. arXiv 2211.17192; EAGLE-3 arXiv 2503.01840; our spec_results loss was all round trip; PENDING run here |
| 2 | Route on a cheap prompt feature first, and skip the 30B for open chat | Replay shows 94% of chat climbs anyway; skipping saves the wasted 30B call and its latency | Low | Low | `results_replay.md` |
| 3 | Check cache hits with a test or judge before serving | Replay: 82 of 97 near-repeat pairs not interchangeable | Medium | Low | `results_replay.md`, `results_bank.md` (tests caught 0 wrong, since hits were right) |
| 4 | Keep one warm self-hosted GPU only if traffic is steady | Avoids paying $4.5 per hour idle | Low | Low | `results_modal.md` |
| 5 | Cascade by a learned quality estimate instead of token probability | Gate gave 70%, same as a learned router today; needs better features | High | Medium | `results_research_router.md`; FrugalGPT arXiv 2305.05176; RouteLLM arXiv 2406.18665 |
| 6 | Stop LoRA on 763B answers as drawn; try retrieval of verified examples only | LoRA lost 3.9 points | Low | Low | `results_distill.md` |
| 7 | Tree drafting and Medusa-style heads for same-box spec | Papers: further 1.2x to 1.5x | High | Medium | Medusa arXiv 2401.10774; SpecInfer arXiv 2305.09781 |

## 6. Verdict (PENDING)

To fill after the runs, naming failures.

## 7. Open questions for the user

1. Is the product goal lower cost or lower latency? The ladder cuts cost on repeats and trivial code and raises latency on chat.
2. May we serve a big model ourselves (steady traffic) or stay on Crusoe tokens, which are cheaper than an idle H200?
3. Should spec decoding enter the product at all, given the 763B cannot verify? Only a self-hosted vLLM big model can.
4. Which open question on quality matters most: hard code (78% vs 92%) or open chat?
