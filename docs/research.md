# Research basis

Date: 2026-11-13. Scope: which published ideas fit CHIMERA (cache -> Mac 3B -> GPU 30B -> big cloud model, 50-300 ms links, separate machines), and what was built and measured here.
Abstracts and results were read on arXiv (export API and abs pages). I did not read every method section end to end, and some claimed gains in the table (SpecInfer, Lookahead, Medusa/EAGLE, KV-cache papers, Selective Context) are quoted from memory, not re-checked this session; the rating below leans on the abstract, the setup the paper states, and what the repo's own benchmarks show.

## 1. Papers

| Group | Paper | arXiv |
|---|---|---|
| Speculative decoding | Leviathan et al., Fast Inference via Speculative Decoding | [2211.17192](https://arxiv.org/abs/2211.17192) |
| | Chen et al., Speculative Sampling | [2302.01318](https://arxiv.org/abs/2302.01318) |
| | SpecInfer (token trees) | [2305.09781](https://arxiv.org/abs/2305.09781) |
| | Medusa | [2401.10774](https://arxiv.org/abs/2401.10774) |
| | EAGLE / EAGLE-2 / EAGLE-3 | [2401.15077](https://arxiv.org/abs/2401.15077), [2406.16858](https://arxiv.org/abs/2406.16858), [2503.01840](https://arxiv.org/abs/2503.01840) |
| | Lookahead decoding | [2402.02057](https://arxiv.org/abs/2402.02057) |
| | Inference with Reference (LLMA, the basis of Prompt Lookup Decoding) | [2304.04487](https://arxiv.org/abs/2304.04487) |
| | REST (retrieval drafts) | [2311.08252](https://arxiv.org/abs/2311.08252) |
| | DistillSpec | [2310.08461](https://arxiv.org/abs/2310.08461) |
| | Online Speculative Decoding | [2310.07177](https://arxiv.org/abs/2310.07177) |
| | Faster Cascades via Speculative Decoding (speculative cascades) | [2405.19261](https://arxiv.org/abs/2405.19261) |
| Edge-cloud | Uncertainty-aware hybrid inference, on-device SLM + remote LLM (U-HLM) | [2412.12687](https://arxiv.org/abs/2412.12687) |
| | Communication-efficient hybrid LM (CU-HLM) | [2505.11788](https://arxiv.org/abs/2505.11788) |
| | Speculative edge-cloud decoding with early exits | [2505.21594](https://arxiv.org/abs/2505.21594) |
| | Pipelined collaborative speculative decoding, edge-cloud | [2603.19133](https://arxiv.org/abs/2603.19133) |
| | Sparse quantize-and-sample SD (wire cost of draft distributions) | [2510.09942](https://arxiv.org/abs/2510.09942) |
| | Edge SLM / cloud LLM collaboration survey | [2507.16731](https://arxiv.org/abs/2507.16731) |
| Routing, cascades | FrugalGPT | [2305.05176](https://arxiv.org/abs/2305.05176) |
| | RouteLLM | [2406.18665](https://arxiv.org/abs/2406.18665) |
| | AutoMix | [2310.12963](https://arxiv.org/abs/2310.12963) |
| | Hybrid LLM (quality-aware routing) | [2404.14618](https://arxiv.org/abs/2404.14618) |
| | LM Cascades: token-level uncertainty and beyond | [2404.10136](https://arxiv.org/abs/2404.10136) |
| Caching | MeanCache (semantic cache, false hits) | [2403.02694](https://arxiv.org/abs/2403.02694) |
| | GPTCache | no arXiv paper; open-source project |
| | Mooncake | [2407.00079](https://arxiv.org/abs/2407.00079) |
| | DistServe | [2401.09670](https://arxiv.org/abs/2401.09670) |
| | Splitwise | [2311.18677](https://arxiv.org/abs/2311.18677) |
| | LMCache | [2510.09665](https://arxiv.org/abs/2510.09665) |
| | CacheGen | [2310.07240](https://arxiv.org/abs/2310.07240) |
| | CacheBlend | [2405.16444](https://arxiv.org/abs/2405.16444) |
| Token reduction | LLMLingua | [2310.05736](https://arxiv.org/abs/2310.05736) |
| | LongLLMLingua | [2310.06839](https://arxiv.org/abs/2310.06839) |
| | LLMLingua-2 | [2403.12968](https://arxiv.org/abs/2403.12968) |
| | Selective Context | [2310.06201](https://arxiv.org/abs/2310.06201) |

## 2. Feasibility against our stack

Network rule used below: a draft/verify round trip costs one 50-300 ms link hop, so any method that needs many round trips per token loses; methods that verify a block per hop or run on one machine are fine. "Spec+" = already built by the Spec+ worker (`inference/specplus.py`), not rebuilt here.

| Technique | What it is | Claimed gain (paper setup) | Fits our network? | Needs | Effort | Expected gain here | Verdict |
|---|---|---|---|---|---|---|---|
| Speculative decoding (2211.17192, 2302.01318) | Small model drafts K tokens, big model checks them in one pass; output distribution unchanged. | 2-3x on T5-XXL / Chinchilla 70B, same accelerator. | Yes if one verify call covers K tokens. | Verifier with prompt logprobs (llama.cpp server). Ollama and Crusoe cannot. | done | Already in repo (`bench/run_spec.py`). | Done |
| Token trees (SpecInfer 2305.09781), adaptive K, pipelining | Several drafts verified in one pass; K tuned by acceptance. | SpecInfer 1.5-3.5x distributed. | Yes, fewer hops. | Tree attention masks on the verifier. | M | Covered by Spec+. | Spec+ covers it |
| Prompt lookup / LLMA (2304.04487), compact wire | Copy n-grams from the prompt as the draft. | Up to ~2-3x on edit/RAG-style tasks. | Yes, no draft model. | Nothing. | S | Covered by Spec+. | Spec+ covers it |
| Medusa, EAGLE 1/2/3 (2401.10774, 2401.15077, 2406.16858, 2503.01840) | Extra decoding heads or feature-level draft model on the target. | 2-6x (EAGLE-3), trained per target model. | Heads sit next to the target, not across a link. | Train heads per target; our targets are hosted APIs. | L | None on hosted tops (Crusoe/GMI give no hidden states). | Skip |
| Lookahead decoding (2402.02057) | Jacobi iteration finds n-grams, no draft model. | 1.5-2x on a single GPU. | Runs inside one server. | Server-side change. | L | None, we do not run the top server. | Skip |
| REST (2311.08252) | Draft from a retrieved datastore of past text. | 1.6-2.4x on 7B/13B code and chat. | Yes, drafts are local. | Datastore + verifier. | M | Needs repeated text; our suite has little. Overlaps prompt lookup. | Later |
| DistillSpec, Online SD (2310.08461, 2310.07177) | Train the draft to match the target. | 10-45% faster (DistillSpec); online: 1.2-3x. | Yes. | Training on target outputs; we log them already. | L | Real, but only after Spec+ is measured on the same pair. | Later |
| Speculative cascades (2405.19261) | Deferral rule that decides per token whether to take the small model's token or defer. | Better cost/quality than cascades or SD alone (Gemma, T5). | Needs both models' token probabilities in one pass: same as SD. | Verifier with logprobs. | M | Overlaps Spec+ accept rule; our token-level signal alone was weak (section 4). | Later |
| U-HLM / CU-HLM (2412.12687, 2505.11788) | Draft side skips the uplink when its uncertainty says the token will be accepted. | 46% fewer uplinks, 97.5% of LLM accuracy (simulation). | Yes, built for slow links. | Calibrated uncertainty threshold. | S | Same signal as our confidence gate; shows the correlation is real but weak per token. | Later |
| Edge-cloud early exit / pipelined SD (2505.21594, 2603.19133) | Overlap drafting with verification so neither side waits. | Up to 35% lower latency (Jetson + A100). | Yes. | Async protocol. | M | Spec+ pipelining covers the same idea. | Spec+ covers it |
| FrugalGPT (2305.05176) | Learned cascade, score each answer, stop when good. | Up to 98% cost cut at GPT-4 quality (their APIs). | Yes. | A scorer trained on labels. | M | Our scorer: token confidence (built). | Partly built |
| RouteLLM, Hybrid LLM (2406.18665, 2404.14618) | Train a router on preference or quality labels to pick the model per query. | RouteLLM >2x cost cut; Hybrid LLM 40% fewer large-model calls, no quality drop. | Yes, decision is local. | Labeled outcomes of both models. | M | Measured here: no gain on our data (section 4). | Built, off |
| AutoMix (2310.12963) | Small model checks its own answer, POMDP picks the next model. | >50% cost cut at equal quality. | Yes. | Extra self-check call per answer. | M | The ladder's `_mid_says_escalate` already does a self-check. | Later |
| LM cascades, token uncertainty (2404.10136) | Use token-level uncertainty quantiles to defer. | Beats mean-probability deferral on some tasks. | Yes. | Token logprobs (have). | S | Feature set in the learned router includes min / first-token / entropy. No lift (section 4). | Built, off |
| MeanCache (2403.02694) | Semantic cache with a trained similarity model and context checks. | +17% F-score, +20% precision, 31% of queries repeat. | Yes, local. | Federated training of the similarity model. | M (full) / S (rules) | Rule version built; small, real cut in false hits (section 4). | Built, off |
| Prompt caching, Mooncake, LMCache, CacheGen, CacheBlend (2407.00079, 2510.09665, 2310.07240, 2405.16444) | Reuse or move KV tensors for repeated long prefixes. | 2-10x prefill/TTFT on long shared contexts. | KV tensors are huge; a 50-300 ms WAN link makes a move slower than recompute for short prompts. Works only between replicas of the same model and tokenizer. | A vLLM KV connector and a shared store. | L | Our suite prompts average 122 tokens in; prefill is not our cost. On Modal, containers of one model could share a store, but the prompts are too short to pay. | Skip (revisit with long contexts) |
| DistServe, Splitwise (2401.09670, 2311.18677) | Split prefill and decode onto different GPUs. | Higher goodput at a latency target. | Inside one cluster, not across our links. | Cluster control. | L | None; we use hosted endpoints. | Skip |
| LLMLingua / LongLLMLingua / LLMLingua-2 (2310.05736, 2310.06839, 2403.12968) | A small model deletes low-information tokens from a long prompt. | Up to 20x compression with little loss; LLMLingua-2 3-6x faster than LLMLingua. | Yes, runs before the call. | A 0.1-0.6 GB encoder; XLM-R-large does not fit the Mac's 1.9 GB free disk. | M | Input is only 18% of top cost in our run (21,938 in vs 23,497 out tokens; $0.0064 of $0.0346). Even 2x compression of every prompt saves at most 9%, and it hurts code. | Later (long-context traffic) |
| Selective Context (2310.06201) | Drop low self-information tokens. | Up to 36% memory / 32% time cut at small quality loss. | Yes. | Small LM. | S | Same limit as LLMLingua: short prompts. | Skip |

## 3. What was built, and why

Picked by expected gain over effort, among things Spec+ does not cover. Both are off by default.

1. **False-hit guard for the semantic cache** (MeanCache, 2403.02694). `packages/chimera-core/cache/guard.py`, hooked into `SemanticCache(guard=...)`; config `[cache] guard = true`. A cosine hit is accepted only if both prompts agree on numbers, negation, named entities and opposite words (min/max, first/last, ...). Reason: the earlier bench served wrong cached answers at 0.94. Rule based, no training, microseconds.
2. **Learned router** (RouteLLM 2406.18665, Hybrid LLM 2404.14618, token-uncertainty cascades 2404.10136). `packages/chimera-core/learned_router.py`, trained by `bench/train_router.py`, weights in `packages/chimera-core/data/router_weights.json`; config `[thresholds] learned_router = "<path>"`. Two logistic models in pure Python: PRE (prompt features, decides to skip the 3B) and POST (prompt + the 3B's token probabilities, decides to keep its answer).

Not built: LLMLingua-2 (cost analysis above says the saving is under 9% on this traffic; the large encoder does not fit the Mac's disk; I did not test the smaller variant), speculative cascades and REST (Spec+ overlap, need a verifier with logprobs).

## 4. Measurements

Single runs, no repeats. Raw rows are in `bench/research_data_local.jsonl` and `bench/research_data_top.jsonl`; full tables in `bench/results_research_router.md` and `bench/results_research_cache.md`. Collection: `bench/run_research_collect.py`.

### 4.1 Cache guard: 800 real QQP validation pairs (296 duplicates), MiniLM cosine

A hit on a non-duplicate pair is a wrong answer from cache. QQP labels are noisy, so true precision is lower than shown for both rows.

| Threshold | Guard | Hits | Correct | Wrong | False-hit rate | Duplicates recalled |
|---|---|---|---|---|---|---|
| 0.97 (shipped) | off | 34 | 30 | 4 | 11.8% | 10.1% |
| 0.97 | on | 29 | 27 | 2 | 6.9% | 9.1% |
| 0.94 | off | 92 | 79 | 13 | 14.1% | 26.7% |
| 0.94 | on | 70 | 63 | 7 | 10.0% | 21.3% |
| 0.90 | off | 172 | 135 | 37 | 21.5% | 45.6% |
| 0.90 | on | 113 | 96 | 17 | 15.0% | 32.4% |

Result: the guard halves wrong hits at 0.97 (4 to 2) and costs 1 point of recall. Counts are small, so the 4-to-2 change is not statistically solid; the direction held at every threshold. On `bench/prompts.jsonl`, 4 of 5 paraphrase pairs pass the guard (cosine 0.94-0.995); the fifth ("biggest one" vs "largest") is rejected, but it was already under 0.97. Even with the guard, 6.9% of hits at 0.97 are still wrong by QQP labels. The guard does not make a 0.9 threshold safe.
Top-model tokens, $ and latency do not change from the guard except through hit count: 5 fewer hits per 800 lookups.

### 4.2 Learned router: 180 graded suite prompts (MMLU 60, HumanEval 55, MBPP 35, GSM8K 30)

Each prompt was answered by the Mac 3B (Qwen2.5-3B q4_k_m) and by the top model (DeepSeek-V4.1-Flash at Crusoe list price). Policies replay those real answers. The GPU mid tier is not in the replay. 3B alone 69.4%, top alone 95.6% ($0.0346, 21,938 tokens in, 23,497 out), best of both 96.7%.

| Score used to decide who answers (3B always runs) | AUC of "3B is right" | Accuracy, 20% sent to top | 40% | 60% |
|---|---|---|---|---|
| Random | 0.50 | 74.7% | 80.0% | 84.9% |
| Keyword `complexity_score` | 0.58 | 75.6% | 82.2% | 87.8% |
| 3B mean token probability (current gate) | 0.64 | 79.4% | 82.8% | 87.2% |
| Learned, prompt features only | 0.59 | 75.0% | 82.8% | 87.8% |
| Learned, prompt + token stats | 0.64 | 77.2% | 85.0% | 88.3% |
| Learned + MiniLM embedding | 0.49 | 75.0% | 79.4% | 83.3% |
| Oracle | 1.00 | 86.7% | 96.7% | 96.7% |

Result: **the gain from the paper does not show up here.** The learned model ties the existing confidence signal (AUC 0.64 vs 0.64) and beats it by 2 points at the 40% budget, which is inside the noise for 180 prompts. On held-out task types the learned model is at or below chance on HumanEval and MBPP (AUC 0.41-0.52 for the prompt-only model). Today's gates are also the bigger issue: the shipped 0.85 confidence gate defers only 2 of 180 prompts and gives 70.0% accuracy, versus 82.8% for the 0.95 gate that sends 72 of 180 (40%) to top for $0.0171 (49% of the top-only cost). So the fix with real measured value is to raise the confidence gate, not to add a router; that change is not made here (it needs the ladder run with the GPU tier).
Latency: median 3.3 s for 3B-only, 4.0 s top-only; all routes sit between, differences under 0.6 s.

Verdict: `learned_router` stays off. Retraining on mixed real traffic (more than 180 rows, and including the GPU tier) is on the roadmap.

## 5. Roadmap (later)

1. Raise `thresholds.confidence` toward 0.95 and measure the full ladder with the GPU tier (`bench/run_ladder.py`); this is the cheapest measured accuracy gain above.
2. Retrain the router on at least 1,000 graded real calls, with the GPU tier as a third outcome, and test per-token deferral inside the speculative verify loop once `bench/spec_results.md` exists.
3. Replace the rule guard with a small trained pair classifier (MeanCache style), and add a context check for multi-turn prompts.
4. DistillSpec / Online SD: fine-tune the 3B on top-model answers we already log, only after Spec+ numbers exist for the same pair.
5. REST-style retrieval drafts from the semantic cache once repeated-prefix traffic is measured.
6. LLMLingua-2 (xlm-roberta variant, run on the GPU box) if prompts grow beyond a few hundred tokens; today input is 18% of top cost.
7. KV-cache sharing across Modal replicas (LMCache connector) only for long shared contexts; same model and tokenizer are required.

## Skipped / not checked

LLMLingua-2 build and test; GMI and Akash GPU tiers (no runs: the replay covers 3B -> top only); `bench/prompts.jsonl` end-to-end with the guard in the full router (only the 5 paraphrase pairs were scored); repeated runs; Dolly and QQP rows of the suite in the router study (not auto-graded).
