# CHIMERA: speculative decoding on Modal, the ladder, and what to change next

2026-11-16. Every number below is a single run and comes from the file named next to it. Losses sit next to wins. Raw speculative-decoding rows are in `bench/.scratch/spec_modal/` (git-ignored); the tables are in [`bench/results_spec_modal.md`](../bench/results_spec_modal.md).

## 1. The answer in one table

The question: can a smaller model on its own GPU box (the "local machine") write tokens that a big model on another box (the "server") only checks, and is that faster than the big model alone? Measured on Qwen3-235B-A22B (FP8, 4x H100) with 48 prompts (28 code, 20 chat, math and short answers), greedy, 256 new tokens.

<svg viewBox="0 0 700 250" xmlns="http://www.w3.org/2000/svg" font-family="Helvetica, Arial, sans-serif" font-size="11">
  <g fill="#111">
    <text x="245" y="24" text-anchor="end">Same box: EAGLE-3 head</text>
    <text x="245" y="48" text-anchor="end">Same box: n-gram lookup</text>
    <text x="245" y="72" text-anchor="end" font-weight="700">235B alone</text>
    <text x="245" y="96" text-anchor="end">Same box: 4B draft model</text>
    <text x="245" y="120" text-anchor="end">Cross-box: 30B drafter, Spec+</text>
    <text x="245" y="144" text-anchor="end">Cross-box: 30B drafter, K=8</text>
    <text x="245" y="168" text-anchor="end">Cross-box: 30B drafter, K=4</text>
    <text x="245" y="192" text-anchor="end">Cross-box: 4B drafter, K=4</text>
    <text x="245" y="216" text-anchor="end">Cross-box: 4B -> 30B -> 235B chain</text>
  </g>
  <g>
    <rect x="252" y="12" width="330" height="16" fill="#2e7d32"/>
    <rect x="252" y="36" width="205" height="16" fill="#66bb6a"/>
    <rect x="252" y="60" width="183" height="16" fill="#546e7a"/>
    <rect x="252" y="84" width="56" height="16" fill="#e57373"/>
    <rect x="252" y="108" width="50" height="16" fill="#e57373"/>
    <rect x="252" y="132" width="46" height="16" fill="#e57373"/>
    <rect x="252" y="156" width="42" height="16" fill="#e57373"/>
    <rect x="252" y="180" width="27" height="16" fill="#e57373"/>
    <rect x="252" y="204" width="15" height="16" fill="#e57373"/>
  </g>
  <g fill="#111">
    <text x="588" y="24">162.2 (1.80x)</text>
    <text x="463" y="48">100.6 (1.12x)</text>
    <text x="441" y="72">89.8</text>
    <text x="314" y="96">27.3 (0.32x)</text>
    <text x="308" y="120">24.4 (0.27x)</text>
    <text x="304" y="144">22.7 (0.25x)</text>
    <text x="300" y="168">20.5 (0.23x)</text>
    <text x="285" y="192">13.2 (0.15x)</text>
    <text x="273" y="216">7.3 (0.09x)</text>
  </g>
  <text x="252" y="242" fill="#555" font-size="10">tok/s, one request at a time; ratio vs the 235B alone in the same Modal account</text>
</svg>

| Finding | Number | Source |
|---|---|---|
| Speculative decoding inside the big model's own box (vLLM's EAGLE-3 head) | 162.2 tok/s vs 89.8, **1.80x faster** | `results_spec_modal.md`, run `a235_big_eagle_q3_235b` |
| A drafter on its own GPU box checked by the big box over the network | 7.3 to 24.4 tok/s, **0.09x to 0.27x** | runs `a235_spec_k4`, `a235_specplus`, `b235_small_spec_k4`, `b235_chain_spec_k4` |
| Same, with the network time taken out of the measured rounds | at most 32 tok/s, **0.37x** | "projected" columns, `results_spec_modal.md` |
| Free speed-up with identical output: n-gram prompt lookup | 100.6 tok/s, **1.12x**, 48/48 identical | run `a235_big_ngram` |

**Verdict.** Do not split drafting and checking across machines for these models. It lost by 4x to 12x, and it would still lose with no network at all. Use speculative decoding inside the box that runs the big model: EAGLE-3 made the 235B 1.8x faster. The Coder-480B and Qwen3.5-397B runs were waiting for GPUs when this was written (section 4); Phase B (other model families) has not run (section 6).

## 2. How the pieces fit today

The ladder picks which model answers a whole prompt. Speculative decoding works inside one model call: a small model writes tokens, a big one checks them.

<svg viewBox="0 0 700 250" xmlns="http://www.w3.org/2000/svg" font-family="Helvetica, Arial, sans-serif" font-size="11">
  <defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#444"/></marker></defs>
  <g fill="#fff" stroke="#444" stroke-width="1.2">
    <rect x="5" y="30" width="90" height="62" rx="6"/>
    <rect x="125" y="30" width="125" height="62" rx="6" fill="#eef6ff"/>
    <rect x="280" y="30" width="125" height="62" rx="6" fill="#eefaf0"/>
    <rect x="435" y="30" width="110" height="62" rx="6" fill="#f4f4f4" stroke-dasharray="4 3"/>
    <rect x="575" y="30" width="120" height="62" rx="6" fill="#fff4e8"/>
    <rect x="125" y="170" width="570" height="30" rx="6" fill="#f7f7f7"/>
  </g>
  <g text-anchor="middle" fill="#111">
    <text x="50" y="65" font-weight="700">Prompt</text>
    <text x="187" y="50" font-weight="700">Tier 0</text><text x="187" y="66">Supabase cache</text><text x="187" y="81">exact, cosine 0.97</text>
    <text x="342" y="50" font-weight="700">Tier 1</text><text x="342" y="66">self-hosted 30B</text><text x="342" y="81">gate p &#8805; 0.95</text>
    <text x="490" y="50" font-weight="700">Tier 2</text><text x="490" y="66">Modal 120B</text><text x="490" y="81">off by default</text>
    <text x="635" y="50" font-weight="700">Tier 3</text><text x="635" y="66">Crusoe 763B</text><text x="635" y="81">top model</text>
    <text x="410" y="190" font-weight="700">Answer to the caller (tier, tokens, ms and $ logged for every call)</text>
  </g>
  <g stroke="#444" stroke-width="1.2" fill="none" marker-end="url(#a)">
    <line x1="95" y1="61" x2="123" y2="61"/><line x1="250" y1="61" x2="278" y2="61"/>
    <line x1="405" y1="61" x2="433" y2="61"/><line x1="545" y1="61" x2="573" y2="61"/>
    <line x1="187" y1="92" x2="187" y2="168"/><line x1="342" y1="92" x2="342" y2="168"/>
    <line x1="490" y1="92" x2="490" y2="168"/><line x1="635" y1="92" x2="635" y2="168"/>
  </g>
  <g fill="#333" font-size="10">
    <text x="252" y="54">miss</text><text x="407" y="54">climb</text><text x="547" y="54">climb</text>
    <text x="192" y="125">hit: ~120 ms, $0</text><text x="347" y="125">passes gate</text><text x="495" y="125">if on</text><text x="640" y="125">always</text>
  </g>
  <path d="M635 200 L635 228 L480 228" stroke="#777" stroke-dasharray="4 3" fill="none" marker-end="url(#a)"/>
  <text x="474" y="232" text-anchor="end" fill="#555" font-size="10">763B answers that pass their tests: stored as teacher data (Supabase teacher_pairs + Aura graph)</text>
</svg>

<svg viewBox="0 0 700 150" xmlns="http://www.w3.org/2000/svg" font-family="Helvetica, Arial, sans-serif" font-size="11">
  <defs><marker id="b" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#444"/></marker></defs>
  <text x="10" y="14" font-weight="700">Cross-box (measured here): one network round trip per round</text>
  <rect x="20" y="22" width="200" height="50" rx="6" fill="#eefaf0" stroke="#444"/>
  <rect x="480" y="22" width="200" height="50" rx="6" fill="#fff4e8" stroke="#444"/>
  <g text-anchor="middle"><text x="120" y="43" font-weight="700">Drafter box (1 L40S)</text><text x="120" y="59">writes K tokens</text>
  <text x="580" y="43" font-weight="700">Big box (4 H100)</text><text x="580" y="59">checks all K in one pass</text></g>
  <line x1="222" y1="38" x2="478" y2="38" stroke="#444" marker-end="url(#b)"/><text x="350" y="32" text-anchor="middle">context + K draft token ids (HTTPS)</text>
  <line x1="478" y1="58" x2="222" y2="58" stroke="#444" marker-end="url(#b)"/><text x="350" y="72" text-anchor="middle">accepted count + the big model's next token</text>
  <text x="10" y="102" font-weight="700">Same box (vLLM's own): no network, the draft step runs next to the big model</text>
  <rect x="20" y="110" width="660" height="32" rx="6" fill="#eef6ff" stroke="#444"/>
  <text x="350" y="131" text-anchor="middle">Big box: EAGLE-3 head, n-gram lookup, a small draft model, or the model's own MTP layer</text>
</svg>

Speculative decoding is not in the product ladder. The 763B on Crusoe rejects `echo`, so it cannot score draft tokens, and Ollama returns no prompt logprobs. Only a self-hosted vLLM (or llama.cpp) big model can check drafts, so speculative decoding belongs inside a self-hosted tier, not between tiers.

## 3. Where the time goes in a cross-box round

<svg viewBox="0 0 700 170" xmlns="http://www.w3.org/2000/svg" font-family="Helvetica, Arial, sans-serif" font-size="11">
  <g fill="#111">
    <text x="215" y="26" text-anchor="end">Cross-box round, K=4</text>
    <text x="215" y="58" text-anchor="end">Same 4.14 tokens, 235B alone</text>
    <text x="215" y="100" text-anchor="end">Big box check, at most 16 tokens</text>
    <text x="215" y="132" text-anchor="end">Big box check, over 16 tokens</text>
  </g>
  <rect x="222" y="14" width="70" height="18" fill="#81c784"/><rect x="292" y="14" width="89" height="18" fill="#ffb74d"/><rect x="381" y="14" width="62" height="18" fill="#90a4ae"/>
  <text x="257" y="27" text-anchor="middle" font-size="10">draft 47</text><text x="336" y="27" text-anchor="middle" font-size="10">network 59</text><text x="412" y="27" text-anchor="middle" font-size="10">check 41</text>
  <text x="450" y="27">147 ms</text>
  <rect x="222" y="46" width="65" height="18" fill="#546e7a"/><text x="294" y="59">43 ms (4.14 x 10.4 ms)</text>
  <rect x="222" y="88" width="54" height="18" fill="#90a4ae"/><text x="283" y="101">36 ms</text>
  <rect x="222" y="120" width="314" height="18" fill="#e57373"/><text x="543" y="133">209 ms</text>
  <text x="222" y="160" fill="#555" font-size="10">medians, 1.5 px per ms; account B (K=4 round) and the account C per-round trace (check times)</text>
</svg>

1. **The drafter is not much faster than the big model.** On one L40S the 30B-A3B writes 130 tok/s and the 4B 132 tok/s; the 235B on 4 H100 writes 86 to 90. Speculative decoding pays only when drafting is many times cheaper than the big model's own step. Here four drafted tokens (47 ms) cost more than the big model writing them itself (43 ms).
2. **Checking several tokens costs several decode steps.** A check round of 4 to 16 tokens takes 36 to 37 ms, about 3.5 plain decode steps (10.4 ms each). In a mixture-of-experts model every token picks its own experts, so checking 5 tokens reads far more weights than decoding 1.
3. **A cliff above 16 tokens.** When a round makes the big box compute more than 16 tokens (the context after its last cached 16-token block, plus the draft), the check takes 207 to 215 ms. That hit 26% to 27% of K=4 rounds and most Spec+ rounds, whose K grows to 16. The client-side fix `cap_new` (shrink K in those rounds) is in `bench/spec_modal_core.py` and tested offline; its live measurement was queued on the Coder-480B.
4. **The network.** Modal's public web endpoint added 59 ms per round when both boxes sat in us-east (a bare call: 46 ms). Boxes in us-east and us-west: 91 to 98 ms. Unpinned, the first try put one box in eu-west and the other in ap-southeast: 322 ms. The jobs now put every box in the big box's region.

## 4. Phase A results (Qwen family, below 700B)

| Model | Box | Status | Main numbers |
|---|---|---|---|
| Qwen3-235B-A22B (FP8) | 4x H100 | done, accounts B and C | above; full tables in `results_spec_modal.md` |
| Qwen3-Coder-480B-A35B (FP8), the biggest Qwen3 | 4x H200 | waiting for 4 H200 when written | 28 code prompts; runs: alone, Coder-30B drafter (K=4, and K=4 capped at 16 new tokens), same-box EAGLE-3 |
| Qwen3.5-397B-A17B (FP8), the biggest Qwen3.5 | 4x H200 | not started (credits) | its own tokenizer, so its own chain: 4B and 35B-A3B drafters, MTP |

No open Qwen model is above 700B. The Coder-480B uses the same `tokenizer.json` as every other Qwen3 model (same SHA-256), so Qwen3 drafters can feed it. Qwen3.5 has its own tokenizer (248,320 tokens vs 151,936). DeepSeek's 763B on Crusoe cannot score drafts.

**Is the output the same as the big model alone?** The 235B alone is repeatable: 48/48 identical across two runs and across two accounts.

| Method | Same output as 235B alone |
|---|---|
| Same box: 4B draft model | 48/48 |
| Same box: n-gram | 48/48 |
| Same box: EAGLE-3 | 27/48 |
| Cross-box loop (every drafter, K and Spec+) | 23 to 30 of 48 |

The cross-box loop checks drafts through vLLM's prefill path (`prompt_logprobs`). That path computes slightly different numbers than one-token-at-a-time decoding: scoring the 235B's own answers again in one pass picks a different top token at 76 of 6,544 positions (gaps of 0 to 3 nats; FP8 weights, BF16 logits and a mixture-of-experts router that switches experts when numbers move a little). The outputs drift apart at those near-ties. The loop itself is exact: the offline tests prove it on fake models, and the big box checks it against the real decode at start-up.

**Cold starts** (never inside a speed number): the 235B box took 393 s (account B) and 769 s (account C, empty compile cache) to its first answer; each restart for a same-box method took 313 to 573 s; drafter boxes took 96 to 171 s.

## 5. Every finished result

| Report | Headline | One line | Win or loss |
|---|---|---|---|
| [`bench/results_spec_modal.md`](../bench/results_spec_modal.md) | EAGLE-3 1.80x; cross-box 0.09x to 0.27x | This report: same-box speculative decoding wins, cross-box loses on the 235B. | <span class="mixed">Mixed</span>: win same box, loss across boxes |
| [`bench/results_suite.md`](../bench/results_suite.md) | 763B tokens -38.4%, $ -28.1% | 300 real prompts. Pass 90% vs 93% for the 763B alone; median 86.0 s vs 1.1 s. | <span class="mixed">Mixed</span>: cheaper, slower, 3 points worse |
| [`bench/results_cost_case.md`](../bench/results_cost_case.md) | $11.02 vs $0.158 per 1k calls | 301 coding tasks on the V100 30B (one call at a time): pass 89% vs 95% for the 763B. | <span class="loss">Loss</span> |
| [`bench/results_cost_case_h200.md`](../bench/results_cost_case_h200.md) | $0.070 per 1k calls | The same 30B on a busy H200 (64 at once): cheaper than the 763B ($0.158), pass 90% vs 95%; an idle H200 costs $108.96 a day. | <span class="win">Win</span> only while busy |
| [`bench/results_backend.md`](../bench/results_backend.md) | 97.5% of 763B tokens kept off on repeats | 57 of 60 repeats from the Supabase cache, 0 wrong in 50 graded. First pass kept off only 12.2%; p50 2.34 s vs 0.90 s. | <span class="mixed">Mixed</span>: repeats win, new prompts lose |
| [`bench/results_replay.md`](../bench/results_replay.md) | 763B tokens +9.8% | 300 real oasst1 chats: the 30B answered 18; ladder p50 82.7 s vs 10.6 s for the 763B alone. | <span class="loss">Loss</span> |
| [`bench/results_bank.md`](../bench/results_bank.md) | 75 of 80 served | Solved-problem bank on repeated problems; reworded copies 24 of 80; 0 wrong answers served. | <span class="win">Win</span> on repeats |
| [`bench/results_memory.md`](../bench/results_memory.md) | 68 to 70 of 80 | N+1 memory gave the 30B +2 problems, the same as 3 random stored answers. | <span class="loss">Loss</span> |
| [`bench/results_distill.md`](../bench/results_distill.md) | pass@1 92.2% to 88.3% | LoRA on 2,516 checked 763B answers made the 30B worse on 566 held-out problems. | <span class="loss">Loss</span> |
| [`bench/results_terminal_agent.md`](../bench/results_terminal_agent.md) | 13 of 15 tasks fully local | `chimera code`: 15/15 pass on both paths, $0.00102 vs $0.00415, median 92 s vs 5.5 s per task. | <span class="mixed">Mixed</span>: cheaper, much slower |
| [`bench/spec_results.md`](../bench/spec_results.md) | 0.15x to 0.22x | Mac 3B drafts, V100 30B checks over the internet: 2.1 to 3.3 vs 14.6 tok/s, round trip about 0.6 s. | <span class="loss">Loss</span> |
| [`bench/results_specplus.md`](../bench/results_specplus.md) | 1.14x to 1.22x over plain spec | Stand-in target only: Spec+ 13.4 tok/s vs 19.3 for the big model alone. | <span class="mixed">Mixed</span> |
| [`bench/results_modal.md`](../bench/results_modal.md) | about $0.11 vs $0.0058 | gpt-oss-120b on an H200 before the 763B: 1,352 ms vs 728 ms median, asserts 24/24 on both. | <span class="loss">Loss</span> |
| [`site/docs/ui_results_rooms.md`](../site/docs/ui_results_rooms.md) | 12 report cards | Every report is a card in the castle; numbers are read from the `bench/*.md` files and a drift check fails the tests. | <span class="win">Win</span> |
| [`site/docs/ui_polish.md`](../site/docs/ui_polish.md) | 26/26 and 24/24 checks | WebKit desktop and iPhone, Chrome desktop pass; 57.8 to 60 fps in Chrome. | <span class="win">Win</span> |

## 6. Phase B (other families): ready, not run

| Family | Sizes with one tokenizer | Boxes | Same-box methods | Job |
|---|---|---|---|---|
| Llama 3.1 | 8B, 70B, 405B (FP8, same `tokenizer.json`) | 8B on 1 L40S, 70B on 2 L40S, 405B on 4 H200 | 8B draft model, EAGLE (405B head), n-gram | `qb_llama` |
| gpt-oss | 20B, 120B (o200k_harmony) | 20B on 1 L40S, 120B on 1 H200 | EAGLE-3 head, 20B draft model, n-gram | `qb_gptoss` |
| DeepSeek-V3-0324 | 671B only (no small model shares its tokenizer) | 8 H200 | its own MTP layer, n-gram | `qb_dsv3` |

Why not run: each Modal account used so far has $30 of starter credits, and one 235B job used $21 to $27 of them. The starter plan also refused the 8x H100 fallback and B200 boxes ("unavailable on starter plan"). The 405B and 671B jobs need 4 to 8 H200 for about an hour each. The code and job plans are in `deploy/modal/spec_models.py`.

## 7. Where time and money go

| Cost | Evidence | Reading |
|---|---|---|
| One cross-box round | 147 ms for 4.14 tokens (section 3) | The big model alone writes them in 43 ms |
| One 235B job on Modal | $27.23 (account B, 60 min), $21.32 (account C, 65 min) | 4 H100 at $3.95 each per hour, x1.15 for the region pin |
| A cold start | 393 to 769 s for the 235B; 313 to 573 s per same-box restart | Paid GPU time with no answers |
| Weights on Modal | about 1.25 TB per account at $0.09 per GiB-month | About $110 a month while kept |
| An idle H200 | $108.96 a day (`results_cost_case_h200.md`) | Pays only when kept busy |
| 763B tokens | $0.29/M in, $1.20/M out | So cheap that cheap tiers save little |

## 8. Ranked improvements

Measured means measured in the file named; expected means not measured yet.

| # | Change | Gain | Effort | Risk | Evidence |
|---|---|---|---|---|---|
| 1 | If a big model is self-hosted, turn on vLLM's EAGLE-3 head | 1.80x tok/s, measured | Low: one flag, a 2.4 GB head | Output differs from plain decoding on 21 of 48 prompts (near-ties) | `results_spec_modal.md`; EAGLE-3, arXiv 2503.01840 |
| 2 | Turn on n-gram prompt lookup where EAGLE-3 has no head | 1.12x, identical output 48/48, measured | Low: one flag, no extra memory | Small gain on chat | `results_spec_modal.md`; prompt lookup decoding (Saxena, 2023) |
| 3 | Drop cross-box drafting (a laptop or small box drafting for a remote big model) | Avoids a 4x to 12x slowdown, measured | None | None | `results_spec_modal.md`, `spec_results.md` |
| 4 | Do not use a small draft model for mixture-of-experts targets with few active parameters | 4B for the 30B-A3B: 3.5x slower; 4B inside the 235B box: 0.32x, measured | None | None | `results_spec_modal.md` |
| 5 | Any multi-box GPU setup: same region, or private networking | Bare call 46 ms same region vs 91 to 98 cross-region vs 322 ms cross-continent, measured | Low | Region pin costs 1.15x | `results_spec_modal.md`; Modal i6pn docs |
| 6 | If a remote check is ever needed: keep each check round at 16 new tokens or fewer (`cap_new`) | Check 36 ms instead of 209 ms in 26% of rounds; about 1.3x on cross-box, expected | Low (done in code) | None | per-round trace, `results_spec_modal.md` |
| 7 | Bit-exact speculative output: batch-invariant kernels, or a check endpoint inside vLLM's decode path | Identical output instead of 23 to 30 of 48, expected | Medium | Some speed cost | vLLM batch-invariant mode; root-cause check |
| 8 | Skip the 30B for open chat with a cheap prompt check | Replay: 94% of chats climbed anyway | Low | Low | `results_replay.md` |
| 9 | Check near-repeat cache hits with a test or a judge before serving | Replay: 82 of 97 near-repeat pairs were not interchangeable | Medium | Low | `results_replay.md`, `results_bank.md` |
| 10 | Keep a self-hosted GPU only when traffic keeps it busy | Avoids $108.96 a day idle | Low | Low | `results_cost_case_h200.md`, `results_modal.md` |
| 11 | Route by a learned quality estimate instead of token probability | The learned router tied the gate at 70% | High | Medium | `results_research_router.md`; FrugalGPT, arXiv 2305.05176; RouteLLM, arXiv 2406.18665 |
| 12 | Drop LoRA on 763B answers in this form | LoRA lost 3.9 points | Low | Low | `results_distill.md` |

## 9. Open questions for you

1. **Self-host a big model at all?** EAGLE-3's 1.8x only applies to a big model we run ourselves. Four H100 cost about $15.80 an hour on Modal; the 763B on Crusoe costs $0.158 per 1,000 coding calls.
2. **Modal plan and credits.** Each starter account's $30 ran out after about one big job, and the starter plan blocks 8-GPU H100 boxes and B200. Finishing Phase A (480B, 397B) needs about $25 more; Phase B (405B, 671B, 120B) about $100 to $150. Raise the limit, move to a paid plan, or stop here?
3. **Delete the weight volumes?** About 1.25 TB per account, about $110 a month while kept.
4. **Take cross-box speculative decoding off the roadmap?** Recommended: yes, for every model measured so far.
5. **Is the product goal lower cost or lower latency?** The ladder cuts cost on repeats and trivial code and raises latency on chat; same-box EAGLE-3 cuts latency of a self-hosted big model.
