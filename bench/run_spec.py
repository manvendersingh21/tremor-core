"""Cross-device speculative decoding: Mac Qwen2.5-3B drafts K tokens, GPU Qwen3-30B verifies them.

Per round trip the Mac sends prompt ids + K draft ids and gets back K target logprobs plus sampled
target tokens (correction at the first rejection, or a bonus token if all K pass). Accept rule is
min(1, p_target/p_draft). Both sides sample at temperature 1 so the two distributions are the
plain softmaxes. No KV tensors cross the network; each side keeps its own prefix cache.

Needs: Mac llama-server on :8080, tunnel to the verifier on :18101, (baseline) tunnel to Ollama on :11437 (ssh -f -N -L 127.0.0.1:11437:127.0.0.1:11434 ...).
Run:   .venv/bin/python bench/run_spec.py
"""
from __future__ import annotations

import csv
import json
import pathlib
import statistics as st
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import conftest  # noqa: E402,F401  (registers chimera_core)
from chimera_core.inference.cloud_verifier import CloudVerifier, SpecVerifierBackend  # noqa: E402
from chimera_core.inference.local_draft import LlamaCppTokenizer, chatml  # noqa: E402

DRAFT, VERIFIER, OLLAMA = "http://127.0.0.1:8080", "http://127.0.0.1:18101", "http://127.0.0.1:11437"
IDS = ["e1", "e5", "e7", "e8", "c1", "c2", "c3", "c5", "h1", "h2"]  # filled below if absent
MAX_NEW, KS = 200, (4, 8)
EOS = {151645, 151643}  # <|im_end|>, <|endoftext|>


def post(url: str, body: dict, timeout: float = 300) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (loopback / ssh tunnel)
        return json.load(r)


def draft(ctx: list[int], k: int) -> tuple[list[int], list[float]]:
    d = post(f"{DRAFT}/completion", {"prompt": ctx, "n_predict": k, "n_probs": 1, "temperature": 1.0,
                                     "top_k": 0, "top_p": 1.0, "min_p": 0.0, "cache_prompt": True})
    p = d["completion_probabilities"]
    return [x["id"] for x in p], [x["logprob"] for x in p]


def run_one(tok: LlamaCppTokenizer, backend: SpecVerifierBackend, text: str, k: int) -> dict:
    verifier = CloudVerifier(backend)
    prompt_ids = tok.encode(chatml(text))
    ctx = list(prompt_ids)
    rounds = drafted = accepted = up = down = 0
    t_draft = t_verify = t_server = 0.0
    t0 = time.perf_counter()
    while len(ctx) - len(prompt_ids) < MAX_NEW:
        t = time.perf_counter()
        ids, lps = draft(ctx, k)
        t_draft += time.perf_counter() - t
        if not ids:
            break
        t = time.perf_counter()
        res = verifier.verify(ctx, ids, lps)
        t_verify += time.perf_counter() - t
        t_server += backend.last["ms"] / 1000
        extra = res.correction_id if res.correction_id is not None else backend.last["next_ids"][len(ids)]
        new = res.accepted_ids + [extra]
        rounds += 1
        drafted += len(ids)
        accepted += res.n_accepted
        up += backend.bytes_up
        down += backend.bytes_down
        stop = next((i for i, x in enumerate(new) if x in EOS), None)
        ctx += new if stop is None else new[: stop + 1]
        if stop is not None:
            break
    total = time.perf_counter() - t0
    n_new = len(ctx) - len(prompt_ids)
    return {"K": k, "new_tokens": n_new, "rounds": rounds, "drafted": drafted, "accepted": accepted,
            "alpha": round(accepted / drafted, 3) if drafted else 0.0,
            "tokens_per_round": round(n_new / rounds, 2) if rounds else 0.0,
            "bytes_up_per_round": round(up / rounds) if rounds else 0,
            "bytes_down_per_round": round(down / rounds) if rounds else 0,
            "draft_s": round(t_draft, 2), "verify_rtt_s": round(t_verify, 2),
            "verify_server_s": round(t_server, 2), "total_s": round(total, 2),
            "tok_s": round(n_new / total, 2)}


def ollama_plain(text: str) -> dict:
    t = time.perf_counter()
    d = post(f"{OLLAMA}/api/generate", {"model": "qwen3:30b-instruct", "prompt": chatml(text), "raw": True,
                                        "stream": False, "options": {"num_predict": MAX_NEW, "temperature": 1.0}})
    total = time.perf_counter() - t
    n = d.get("eval_count", 0)
    return {"K": "ollama", "new_tokens": n, "total_s": round(total, 2), "tok_s": round(n / total, 2),
            "decode_tok_s": round(n / (d["eval_duration"] / 1e9), 2) if d.get("eval_duration") else 0}


def main() -> None:
    rows = {json.loads(l)["id"]: json.loads(l) for l in (ROOT / "bench/prompts.jsonl").read_text().splitlines() if l}
    heavy = [i for i, r in rows.items() if r["cat"] == "code_heavy"][:2]
    ids = IDS[:8] + heavy
    tok, backend = LlamaCppTokenizer(DRAFT), SpecVerifierBackend(VERIFIER)

    # tokenizer check: same strings, both sides, compare ids (only verify if all match)
    samples = [chatml(rows[i]["prompt"]) for i in ids] + ["def f(x):\n    return [i**2 for i in range(x)]  # ünï ✓ 日本語"]
    check = [(tok.encode(s) == post(f"{VERIFIER}/tokenize", {"text": s})["ids"]) for s in samples]
    assert all(check), f"tokenizer mismatch on {check.count(False)} of {len(check)} strings"

    rtts = []
    for _ in range(10):
        t = time.perf_counter()
        post(f"{VERIFIER}/tokenize", {"text": "a"})
        rtts.append((time.perf_counter() - t) * 1000)

    post(f"{VERIFIER}/verify", {"prompt_ids": tok.encode("warm"), "draft_ids": [1]})  # warm CUDA/graph
    out = []
    for pid in ids:
        text = rows[pid]["prompt"]
        base = ollama_plain(text)
        out.append({"id": pid, "cat": rows[pid]["cat"], **base})
        for k in KS:
            r = run_one(tok, backend, text, k)
            out.append({"id": pid, "cat": rows[pid]["cat"], **r})
            print(pid, r, flush=True)

    keys = ["id", "cat", "K", "new_tokens", "rounds", "drafted", "accepted", "alpha", "tokens_per_round",
            "bytes_up_per_round", "bytes_down_per_round", "draft_s", "verify_rtt_s", "verify_server_s",
            "total_s", "tok_s", "decode_tok_s"]
    with open(ROOT / "bench/spec_results.csv", "w", newline="") as f:
        w = csv.DictWriter(f, keys, restval="")
        w.writeheader()
        w.writerows(out)
    write_md(out, ids, len(samples), rtts)


def write_md(out: list[dict], ids: list[str], n_tok_checked: int, rtts: list[float]) -> None:
    def sel(k):
        return [r for r in out if r["K"] == k]

    def mean(k, key):
        return st.mean(r[key] for r in sel(k))

    ol = sel("ollama")
    lines = ["# Cross-device speculative decoding results", "",
             "## Setup",
             "- Draft: Mac, llama.cpp `llama-server`, Qwen2.5-3B-Instruct Q4_K_M, `127.0.0.1:8080`, temperature 1 (top_k 0, top_p 1, min_p 0), own prompt cache.",
             "- Target: GPU box (Tesla V100 32 GB), `bench/verify_server.py` (llama-cpp-python, `logits_all`), the same GGUF blob Ollama serves for `qwen3:30b-instruct` (Q4_K_M), 30 of 49 layers on GPU (11.4 GB VRAM; Ollama's 19 GB sits beside it), the other 19 on CPU with 3 threads (the container has a 4-CPU quota and a 27.9 GB RAM cap). Own prefix reuse. Reached through `ssh -L` to `127.0.0.1:18101`.",
             "- Protocol per round trip: Mac sends `prompt_ids + K draft_ids` (JSON ints). GPU returns K target logprobs and one target-sampled token per position. Accept token i with probability min(1, p_target/p_draft). On first rejection the target's sample at that position is appended; if all K pass, the K+1th sample is a free bonus token. No KV tensors move.",
             "- Correction sampling: the target's own sample at the rejection point (existing `CloudVerifier` approximation). Exact lossless decoding would sample from the residual max(0, p_t - p_d), which needs the full draft distribution. Accept/reject math is the exact rule.",
             f"- Prompts: {len(ids)} from `bench/prompts.jsonl` ({', '.join(ids)}), max {MAX_NEW} new tokens, K in {list(KS)}. One run each, sampled output, so numbers are noisy.",
             f"- Baseline: plain generation on the GPU box by Ollama `qwen3:30b-instruct` (all layers on GPU, raw ChatML prompt, temperature 1), timed from the Mac through the same kind of ssh tunnel (`:11437`). Other workers were using the same box during the run (Ollama's runner at about 300% CPU of the 4-CPU quota), so the verifier's 19 CPU layers were starved; see verdict.",
             "",
             "## Tokenizer check",
             f"The Mac draft tokenizer (`/tokenize`, special tokens parsed) and the GPU target tokenizer (llama.cpp on the Qwen3 GGUF) produced identical ids on {n_tok_checked} of {n_tok_checked} strings (the ChatML-wrapped test prompts plus a unicode/code string). The script asserts this before verifying anything.",
             "",
             f"Round-trip floor to the verifier (tiny `/tokenize` call through the tunnel, 10 calls): median {st.median(rtts):.0f} ms, min {min(rtts):.0f} ms.",
             "",
             "## Per prompt (alpha = accepted draft tokens / drafted)", "",
             "| prompt | cat | alpha K=4 | alpha K=8 | tok/round K=4 | tok/round K=8 | spec tok/s K=4 | spec tok/s K=8 | Ollama tok/s |",
             "|---|---|---|---|---|---|---|---|---|"]
    by = {(r["id"], r["K"]): r for r in out}
    for pid in ids:
        a, b, o = by[(pid, 4)], by[(pid, 8)], by[(pid, "ollama")]
        lines.append(f"| {pid} | {o['cat']} | {a['alpha']} | {b['alpha']} | {a['tokens_per_round']} | "
                     f"{b['tokens_per_round']} | {a['tok_s']} | {b['tok_s']} | {o['tok_s']} |")
    lines += ["", "## Means", "", "| | K=4 | K=8 |", "|---|---|---|"]
    for key, label in [("alpha", "alpha (mean of per-prompt)"), ("tokens_per_round", "tokens per round trip (accepted + 1)"),
                       ("bytes_up_per_round", "bytes up per round trip"), ("bytes_down_per_round", "bytes down per round trip"),
                       ("tok_s", "speculative tokens/sec (wall clock)")]:
        lines.append(f"| {label} | {mean(4, key):.2f} | {mean(8, key):.2f} |")
    for key, label in [("draft_s", "draft time per prompt (s)"), ("verify_rtt_s", "verify round trips per prompt (s)"),
                       ("verify_server_s", "of which GPU compute (s)")]:
        lines.append(f"| {label} | {mean(4, key):.2f} | {mean(8, key):.2f} |")
    sp4, sp8, olm = mean(4, "tok_s"), mean(8, "tok_s"), st.mean(r["tok_s"] for r in ol)
    lines += ["", f"Plain Ollama on the GPU box: mean {olm:.2f} tok/s wall clock (decode only, server side: {st.mean(r['decode_tok_s'] for r in ol):.2f} tok/s).",
              "", "## Verdict", "",
              f"Speculative tok/s vs plain Ollama: K=4 {sp4 / olm:.2f}x, K=8 {sp8 / olm:.2f}x (1.00x = same speed).", "",
              "VERDICT_PLACEHOLDER (written by hand from the numbers above after each run)", ""]
    (ROOT / "bench/spec_results.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
