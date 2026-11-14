# N+1 training: LoRA on 763B-verified solutions (single run)

**Verdict: the LoRA made the 30B worse.** pass@1 on 566 held-out problems fell from 92.2% to 88.3% (522 -> 500 passed). Paired: 26 problems only the base solved, 4 only the tuned model solved (sign test p < 0.001). The loss is on HumanEval (-9.8 points) and MBPP test (-2.7). The cost-case tasks did not move. One run, one seed, one learning rate; this does not show that weight training cannot work, only that this recipe did not.

## Setup

| Item | Value |
|---|---|
| Teacher | Crusoe `deepseek-ai/DeepSeek-V4.1-Flash` (763B), thinking off, temp 0 |
| Student | `Qwen/Qwen3-30B-A3B-Instruct-2507` (HF checkpoint, same family as the Akash `qwen3:30b-instruct`), bf16 |
| Method | LoRA r=16, alpha 32, dropout 0.05, on `q_proj k_proj v_proj o_proj` only (13.4M trainable of 30.5B). Experts are fused tensors that peft cannot wrap, so they are frozen |
| Training | HF `Trainer`, 1 epoch, 158 steps, batch 16, lr 2e-4 cosine, max length 1024, loss on answer tokens only. Loss 0.32 (first log) -> 0.07 (last), mean 0.094 |
| Hardware | Modal H200, torch 2.8, transformers 4.57.1, peft 0.17.1. Script: `deploy/modal/distill.py` |
| Eval | vLLM v0.33.0 offline batch on the same H200, base then merged weights, same prompts, temp 0, max 1,500 tokens, no thinking (the Instruct-2507 model has none). Graded by `bench/datasets/grade.py` (sandboxed unit tests) |
| Memory store | Pairs went to a JSONL in `bench/.scratch/distill/` (git-ignored), not `memory.store()`. That call writes the shared `teacher_pairs` table and the Aura graph, and 2,500 bulk pairs would swamp the retrieval chat's data |

A first 2-epoch run was stopped after 3 steps (28 s/step, about 2.5 h, close to the 3 h function limit) and restarted with 1 epoch.

## Data

| Count | Value |
|---|---|
| Train problems sampled | 4,960: MBPP train 374, validation 90, prompt 10 (MBPP full-config ids that are not in the test split) and 4,486 from 45 random pages of AceCode-87K (`TIGER-Lab/AceCode-87K`, assert-style tests) |
| Dropped for overlap with the held-out set | 680 (MBPP 126, AceCode 554) |
| Sent to the 763B | 4,280 |
| Passed their tests, kept | **2,516** (AceCode 2,210; MBPP 306) |
| Not kept | 1,764. Only 2,792 calls got an API answer, so about 1,488 of the 4,280 got none (timeouts or errors after 4 tries) and count as failed. The solve step resumes, so a rerun would add pairs; I did not retrain on them |

**Overlap check** (`build_data.py overlap`, `overlap_ids`): a train problem is dropped if its text shares any 8-word sequence with a held-out problem, has word-set Jaccard >= 0.6 with one, or has the same first test line. 680 of 4,960 were flagged, 679 by the 8-gram rule. This is strict on purpose and will also drop some harmless pairs. It cannot catch a paraphrase with different words. MBPP test (ids 11-510) is disjoint from the train/validation/prompt splits by id.

## Held-out set (566 problems)

HumanEval all 164, MBPP sanitized test 257, and the 145 custom tasks of the cost case (`bench/cost_case/tasks.jsonl`, the HumanEval and MBPP items there are already in the first two sets). `bench/results_cost_case.md` did not exist yet, so the numbers are not lined up with it beyond using the same tasks and grader.

## Results: pass@1, temp 0

| Category | n | Base 30B | Base + LoRA | Change |
|---|---|---|---|---|
| HumanEval | 164 | 96.3% (158) | 86.6% (142) | -9.8 pts |
| MBPP test | 257 | 88.7% (228) | 86.0% (221) | -2.7 pts |
| Cost case, trivial | 101 | 98.0% (99) | 99.0% (100) | +1.0 pt |
| Cost case, everyday | 38 | 89.5% (34) | 89.5% (34) | 0 |
| Cost case, hard | 6 | 50.0% (3) | 50.0% (3) | 0 |
| **All** | 566 | **92.2%** (522) | **88.3%** (500) | **-3.9 pts** |

Paired: both pass 496, neither 40, base only 26, tuned only 4. Output tokens over the 566 answers: base 47,002, tuned 30,474 (-35%).

## Why it likely lost (a reading, not tested)

The tuned answers are shorter. The 763B's answers in the training set are bare code blocks, and the student learned to write bare code at once. Looking at the first HumanEval failures, the tuned model skips the extra working the base does inside the block and gets logic wrong (for example `make_palindrome`, `is_multiply_prime`). The training prompts were MBPP style (task text, three tests), while HumanEval is "complete this stub", so that format shift hurts most there. Untested fixes: a lower learning rate or rank, keeping a mix of the base model's own correct answers, training on HumanEval-style stub prompts, a larger and cleaner set.

## Not done

- **Retrieval memory comparison:** `bench/results_memory.md` does not exist yet, so there is nothing to compare with. The harness is `bench/memory/run_memory.py`.
- No repeat runs, no second learning rate, no category for problems the base fails and the 763B solves.
- Held-out grading used my sandboxed runner only; no second grader.
- The pairs were not scrubbed through `memory/safety.py` because they never entered the memory store. They are public dataset text plus model code.

## Cost

| Item | Cost |
|---|---|
| Crusoe 763B, 2,792 calls, 687k in / 246k out tokens | **$0.49** at list price ($0.29 in / $1.20 out per M) |
| Modal H200 | about **$8**: roughly 1.8 GPU hours (the stopped run, training 44 min plus load, merge and save, two eval runs) at a list price near $4.5 per hour. Estimated from wall time, not read from the bill |
| Total | about $8.5, under the $60 stop line |

The H200 is off: `modal app list` showed no running app of ours at the end. Functions have no web endpoint and `scaledown_window=60`.

## Getting the adapter to the Akash box (not done, do not install yet)

1. Merged bf16 weights are already in the Modal volume `chimera-distill` at `/out/merged` (the adapter alone is at `/out/adapter`).
2. Convert on a machine with disk: `modal volume get chimera-distill /out/merged ./merged`, then llama.cpp `convert_hf_to_gguf.py ./merged --outtype q8_0`, or quantize to q4_k_m with `llama-quantize`.
3. On the box, create a **new** model name so `qwen3:30b-instruct` is untouched: `ollama create qwen3-30b-n1 -f Modelfile` with `FROM ./merged-q4_k_m.gguf` and the Qwen chat template.
4. Given the result above, do not do this with the current adapter.

## Reproduce

`bench/distill/build_data.py` (`heldout`, `problems`, `solve`, `overlap`), `deploy/modal/distill.py` (`download`, `train`, `evaluate`), `bench/distill/grade_gen.py`. Eval rows are in `bench/.scratch/distill/eval_log.jsonl` (run id `distill-v1`, 1,132 rows), read by `bench/evallog.py`.
