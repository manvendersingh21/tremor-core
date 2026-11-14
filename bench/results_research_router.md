# Learned router (RouteLLM / Hybrid LLM / token-uncertainty deferral) on the real suite

Data: 180 auto-graded prompts from `bench/datasets/suite.jsonl` (gsm8k 30, humaneval 55, mbpp 35, mmlu 60). Each prompt was answered by the Mac 3B (Qwen2.5-3B q4_k_m) AND by the top model (DeepSeek-V4.1-Flash, thinking off), so every policy below is replayed on real outputs. The mid GPU tier is not in this replay (3B -> top only). Single run, no repeats. Probabilities are out-of-fold (5-fold CV); the threshold of each learned policy is then picked on those same out-of-fold scores, so the matched-quality rows are slightly optimistic.

3B alone: 69.4% correct. Top alone: 95.6%. Oracle (best of both per prompt): 96.7%.

| policy | accuracy | top calls | top tokens in | top tokens out | top $ | median s | mean s |
|---|---|---|---|---|---|---|---|
| top only | 95.6% | 180 | 21938 | 23497 | $0.0346 | 4.0 | 6.9 |
| 3B only | 69.4% | 0 | 0 | 0 | $0.0000 | 3.3 | 6.0 |
| BASELINE: complexity_score>=0.6 -> top, else 3B if confidence>=0.85 | 70.0% | 2 | 210 | 4 | $0.0001 | 3.3 | 6.0 |
| learned PRE only (skip 3B when P(ok) low; keep every 3B answer otherwise) @t=0.33 | 70.0% | 1 | 131 | 298 | $0.0004 | 3.2 | 5.9 |
| learned POST only (3B always runs; keep if P(ok) high) @t=0.20 | 70.0% | 1 | 131 | 298 | $0.0004 | 3.3 | 6.0 |
| learned PRE+POST @pre=0.33,post=0.20 | 70.0% | 1 | 131 | 298 | $0.0004 | 3.3 | 6.0 |

## Equal top-call budget (3B always runs; the k lowest-scored prompts go to top)

| score used to defer | AUC | acc @20% to top | acc @40% | acc @60% | top $ @40% |
|---|---|---|---|---|---|
| oracle (knows if 3B is right) | 1.00 | 86.7% | 96.7% | 96.7% | $0.0179 |
| 3B mean token probability (the 0.85 gate's signal) | 0.64 | 79.4% | 82.8% | 87.2% | $0.0171 |
| keyword complexity_score (inverted) | 0.58 | 75.6% | 82.2% | 87.8% | $0.0215 |
| learned PRE (prompt features) | 0.59 | 75.0% | 82.8% | 87.8% | $0.0195 |
| learned POST (prompt + token stats) | 0.64 | 77.2% | 85.0% | 88.3% | $0.0196 |
| learned POST + MiniLM embedding (not shipped) | 0.49 | 75.0% | 79.4% | 83.3% | $0.0163 |
| random deferral (mean of 200 draws) | 0.50 | 74.7% | 80.0% | 84.9% | |

Confidence-gate baseline sweep (3B always runs, keep if mean token probability >= t):

| policy | accuracy | top calls | top tokens in | top tokens out | top $ | median s | mean s |
|---|---|---|---|---|---|---|---|
| conf>=0.7 | 69.4% | 0 | 0 | 0 | $0.0000 | 3.3 | 6.0 |
| conf>=0.8 | 69.4% | 0 | 0 | 0 | $0.0000 | 3.3 | 6.0 |
| conf>=0.85 | 70.0% | 2 | 210 | 4 | $0.0001 | 3.3 | 6.0 |
| conf>=0.9 | 73.9% | 13 | 1549 | 1375 | $0.0021 | 3.5 | 6.1 |
| conf>=0.95 | 82.8% | 72 | 9112 | 12032 | $0.0171 | 3.9 | 6.4 |

Leave-one-source-out (train on 3 sources, score the 4th; AUC of P(3B correct)):

| source | n | 3B acc | AUC pre | AUC post | AUC mean-confidence | AUC complexity_score (inverted) |
|---|---|---|---|---|---|---|
| gsm8k | 30 | 73% | 0.65 | 0.59 | 0.88 | 0.80 |
| humaneval | 55 | 69% | 0.48 | 0.52 | 0.54 | 0.51 |
| mbpp | 35 | 54% | 0.41 | 0.64 | 0.73 | 0.46 |
| mmlu | 60 | 77% | 0.51 | 0.52 | 0.56 | 0.59 |

Overall AUC (5-fold): pre 0.59, post 0.64, mean-confidence 0.64, complexity_score 0.58.
