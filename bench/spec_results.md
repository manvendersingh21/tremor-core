# Cross-device speculative decoding results

## Setup
- Draft: Mac, llama.cpp `llama-server`, Qwen2.5-3B-Instruct Q4_K_M, `127.0.0.1:8080`, temperature 1 (top_k 0, top_p 1, min_p 0), own prompt cache.
- Target: GPU box (Tesla V100 32 GB), `bench/verify_server.py` (llama-cpp-python, `logits_all`), the same GGUF blob Ollama serves for `qwen3:30b-instruct` (Q4_K_M), 30 of 49 layers on GPU (11.4 GB VRAM; Ollama's 19 GB sits beside it), the other 19 on CPU with 3 threads (the container has a 4-CPU quota and a 27.9 GB RAM cap). Own prefix reuse. Reached through an `ssh -L` tunnel.
- Protocol per round trip: Mac sends `prompt_ids + K draft_ids` (JSON ints). GPU returns K target logprobs and one target-sampled token per position. Accept token i with probability min(1, p_target/p_draft). On first rejection the target's sample at that position is appended; if all K pass, the K+1th sample is a free bonus token. No KV tensors move.
- Correction sampling: the target's own sample at the rejection point (existing `CloudVerifier` approximation). Exact lossless decoding would sample from the residual max(0, p_t - p_d), which needs the full draft distribution. Accept/reject math is the exact rule.
- Prompts: 10 from `bench/prompts.jsonl` (e1, e5, e7, e8, c1, c2, c3, c5, h1, h2), max 200 new tokens, K in [4, 8]. One run each, sampled output, so numbers are noisy.
- Baseline: plain generation on the GPU box by Ollama `qwen3:30b-instruct` (all layers on GPU, raw ChatML prompt, temperature 1), timed from the Mac through the same kind of ssh tunnel (`:11437`). Other workers were using the same box during the run (Ollama's runner at about 300% CPU of the 4-CPU quota), so the verifier's 19 CPU layers were starved; see verdict.

## Tokenizer check
The Mac draft tokenizer (`/tokenize`, special tokens parsed) and the GPU target tokenizer (llama.cpp on the Qwen3 GGUF) produced identical ids on 11 of 11 strings (the ChatML-wrapped test prompts plus a unicode/code string). The script asserts this before verifying anything.

Round-trip floor to the verifier (tiny `/tokenize` call through the tunnel, 10 calls): median 599 ms, min 495 ms.

## Per prompt (alpha = accepted draft tokens / drafted)

| prompt | cat | alpha K=4 | alpha K=8 | tok/round K=4 | tok/round K=8 | spec tok/s K=4 | spec tok/s K=8 | Ollama tok/s |
|---|---|---|---|---|---|---|---|---|
| e1 | easy | 1.0 | 1.0 | 4.0 | 8.0 | 1.55 | 6.23 | 2.05 |
| e5 | easy | 0.507 | 0.188 | 3.0 | 2.43 | 1.46 | 0.7 | 18.34 |
| e7 | easy | 0.662 | 0.375 | 3.64 | 4.0 | 1.36 | 0.98 | 20.25 |
| e8 | easy | 0.512 | 0.25 | 2.91 | 2.79 | 1.67 | 0.58 | 10.28 |
| c1 | code_small | 0.77 | 0.619 | 3.88 | 5.64 | 2.77 | 4.44 | 2.32 |
| c2 | code_small | 0.947 | 0.941 | 4.74 | 8.18 | 1.71 | 6.91 | 19.06 |
| c3 | code_small | 0.973 | 0.736 | 4.5 | 6.43 | 3.51 | 6.03 | 18.2 |
| c5 | code_small | 0.694 | 0.575 | 3.7 | 5.6 | 3.97 | 3.44 | 20.17 |
| h1 | code_heavy | 0.485 | 0.267 | 2.94 | 3.14 | 1.72 | 1.43 | 19.98 |
| h2 | code_heavy | 0.253 | 0.239 | 2.01 | 2.91 | 1.64 | 2.0 | 15.33 |

## Means

| | K=4 | K=8 |
|---|---|---|
| alpha (mean of per-prompt) | 0.68 | 0.52 |
| tokens per round trip (accepted + 1) | 3.53 | 4.91 |
| bytes up per round trip | 679.90 | 687.50 |
| bytes down per round trip | 136.30 | 212.20 |
| speculative tokens/sec (wall clock) | 2.14 | 3.27 |
| draft time per prompt (s) | 7.13 | 15.49 |
| verify round trips per prompt (s) | 57.14 | 62.07 |
| of which GPU compute (s) | 38.16 | 46.78 |

Plain Ollama on the GPU box: mean 14.60 tok/s wall clock (decode only, server side: 21.99 tok/s).

## Verdict

Speculative tok/s vs plain Ollama: K=4 0.15x, K=8 0.22x (1.00x = same speed).

**Speculative decoding across the internet was 4.5x to 7x slower than plain Ollama on this setup.** The protocol works (ids match, only small int/float arrays cross, alpha is real), but no prompt beat Ollama except where Ollama itself was slow (e1, c1: model reload or queueing behind another worker, 3.9 s for 8 tokens and 26.7 s for 62).

Where the time goes, per round trip (from the CSV):

| part | K=4 | K=8 | plain Ollama, same tokens |
|---|---|---|---|
| network floor | ~0.55 s | ~0.55 s | 0 (one request) |
| verifier GPU+CPU pass | 0.5-2.0 s | 0.4-3.2 s | - |
| Mac draft | ~0.2 s | ~0.3-1.3 s | - |
| tokens gained | 3.5 | 4.9 | 3.5-4.9 tokens in ~0.16-0.22 s at 22 tok/s |

1. The internet round trip alone (median 599 ms) caps the method at about 3.5/0.6 = 6 tok/s (K=4) or 8 tok/s (K=8), even with a free verifier. Ollama decodes at 22 tok/s. So the network by itself cancels the gain.
2. The verifier is far slower than Ollama per pass: 19 of 49 layers run on 3 CPU threads under a 4-CPU container quota shared with Ollama and other workers. Full GPU offload is not possible while Ollama holds 19 GB of the 32 GB.
3. Alpha is good on short code (c2 0.95, c3 0.97 at K=4) and poor on long prose and heavy code (h2 0.25). Mean alpha 0.68 (K=4), 0.52 (K=8). K=8 wins on code, K=4 on prose.
4. Bytes per round trip are small (about 0.7 KB up, 0.1-0.25 KB down) but grow with the prompt, because the verifier is stateless and gets the full ids each time. Sending only new ids would cut this to under 100 bytes; it would not change speed.

When it could pay off: verifier with all layers on GPU, round trip under ~50 ms (same LAN or same data center), and code-like output with alpha above 0.7. None of these hold here.

Restart: on the GPU box `bash bench/start_verifier.sh` (copied to the box) (load ~4 min), then on the Mac `ssh -f -N -L 127.0.0.1:18101:127.0.0.1:18101 <gpu-host>` and `ssh -f -N -L 127.0.0.1:11437:127.0.0.1:11434 ...` for the baseline; run `.venv/bin/python bench/run_spec.py`. Stop: `pkill -f "[v]erify_server.py"` on the box (the brackets stop pkill matching its own ssh shell); `pkill -f "ssh -f -N -L 127.0.0.1:18101"` and `pkill -f "ssh -f -N -L 127.0.0.1:11437"` on the Mac.
