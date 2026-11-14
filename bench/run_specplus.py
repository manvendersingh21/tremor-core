"""Spec+ vs plain speculative decoding. Writes bench/results_specplus.md and .csv.

Real parts: the Mac Qwen2.5-3B (llama.cpp, 127.0.0.1:8080) drafts real text, and its real per-call
latency is charged to the virtual clock. Modelled parts: the network round trip and the verifier's
compute time. The stand-in target is the same 3B with its distribution sharpened (T=0.6, top-16),
because no Qwen-vocab verifier was reachable (see the report). Everything is labelled in the md.

Needs `bench/serve_local.sh` running. Run: .venv/bin/python bench/run_specplus.py [--quick]
"""
from __future__ import annotations

import csv
import json
import math
import os
import pathlib
import pickle
import random
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import conftest  # noqa: E402,F401
from chimera_core.inference import specplus as sp  # noqa: E402
from chimera_core.inference.local_draft import LlamaCppTokenizer, chatml  # noqa: E402

DRAFT = "http://127.0.0.1:8080"
T_TARGET, TOPN, MAX_NEW = 0.6, 16, 96
MEMO = pathlib.Path(os.environ.get("KIROCREW_SCRATCH", "/tmp")) / "specplus_memo.pkl"

CODE = ("def total_price(items, tax):\n    result = 0\n    for item in items:\n"
        "        result += item['price'] * item['qty']\n    return result * (1 + tax)\n")
EDITS = [
    f"Rename the variable `result` to `subtotal` and add a docstring. Return the full function.\n\n{CODE}",
    f"Add type hints and make it skip items whose qty is 0. Return the full function.\n\n{CODE}",
    f"Rewrite this function using sum() and a generator expression. Return the full function.\n\n{CODE}",
    "Fix the bug (it divides by zero on an empty list) and return the full function.\n\n"
    "def mean(xs):\n    total = 0\n    for x in xs:\n        total += x\n    return total / len(xs)\n",
    "Add logging of each call at INFO level and return the full function.\n\n"
    "def add(a, b):\n    return a + b\n",
]
MATH = ["Compute 37 * 43 step by step.", "Solve 3x + 7 = 25 for x and explain each step.",
        "What is the sum of the first 20 odd numbers? Show the reasoning."]
CHAT = ["Give me three tips for a first-time marathon runner.",
        "Explain in a short paragraph why the sky is blue."]
FROM_FILE = ["c1", "c2", "c5", "e5", "p4", "e9", "p5"]  # p4/e5 and p5/e9 are paraphrase pairs (cache neighbours)


def prompts() -> list[tuple[str, str]]:
    rows = {json.loads(l)["id"]: json.loads(l) for l in (ROOT / "bench/prompts.jsonl").read_text().splitlines() if l}
    out = [(f"edit{i + 1}", t) for i, t in enumerate(EDITS)] + [(f"math{i + 1}", t) for i, t in enumerate(MATH)]
    out += [(f"chat{i + 1}", t) for i, t in enumerate(CHAT)] + [(i, rows[i]["prompt"]) for i in FROM_FILE]
    return out


def post(url: str, body: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:  # noqa: S310 (loopback)
        return json.load(r)


class Model:
    """One llama-server call per context gives the draft top-16 (T=1); the stand-in target is that
    list sharpened to T=0.6. Calls are memoised, and the first measured latency is charged."""

    def __init__(self) -> None:
        self.memo: dict[tuple, tuple[list, float]] = pickle.loads(MEMO.read_bytes()) if MEMO.exists() else {}
        self.calls = 0

    def _get(self, ctx):
        k = tuple(ctx)
        if k not in self.memo:
            t = time.perf_counter()
            d = post(f"{DRAFT}/completion", {"prompt": list(ctx), "n_predict": 1, "n_probs": TOPN, "temperature": 1.0,
                                             "top_k": 0, "top_p": 1.0, "min_p": 0.0, "cache_prompt": True})
            top = [(x["id"], x["logprob"]) for x in d["completion_probabilities"][0]["top_logprobs"]][:TOPN]
            self.memo[k] = (top, time.perf_counter() - t)
            self.calls += 1
        return self.memo[k]

    def top(self, ctx):
        return self._get(ctx)

    def dist(self, ctx):
        w = {i: math.exp(lp / T_TARGET) for i, lp in self._get(ctx)[0]}
        s = sum(w.values())
        return {i: x / s for i, x in w.items()}

    def save(self) -> None:
        MEMO.write_bytes(pickle.dumps(self.memo))


def cos(a: str, b: str) -> float:
    wa, wb = set(a.lower().split()), set(b.lower().split())
    return len(wa & wb) / math.sqrt(len(wa) * len(wb) or 1)


def run(cfg: sp.Cfg | None, model: Model, items, base: sp.Cfg, use_free: bool) -> sp.Stats:
    tot = sp.Stats()
    answers: list[tuple[str, list[int]]] = []
    for pid, text, ids in items:
        rng = random.Random(f"{pid}")
        if cfg is None:
            st = sp.autoregressive(ids, model, base, rng)
        else:
            nb = None
            if use_free and answers:  # best earlier answer by prompt similarity, used even below 0.97
                nb = max(((cos(text, t), a) for t, a in answers), key=lambda x: x[0])[1]
            st = sp.generate(ids, model, model, cfg, rng, sp.FreeDrafter(nb) if cfg.free else None)
        answers.append((text, st.out))
        for f in sp.Stats.__dataclass_fields__:
            if f != "out":
                setattr(tot, f, getattr(tot, f) + getattr(st, f))
    return tot


def configs(rtt: float, srv: float) -> list[tuple[str, sp.Cfg | None]]:
    b = dict(rtt=rtt, srv_base=srv, max_new=MAX_NEW)
    allf = dict(adaptive=True, tree=True, pipeline=True, free=True, binary=True)
    return [("big model alone", None), ("plain spec K=4", sp.Cfg(k=4, **b)), ("plain spec K=8", sp.Cfg(k=8, **b)),
            ("+ adaptive K", sp.Cfg(adaptive=True, **b)), ("+ token tree (K=4)", sp.Cfg(k=4, tree=True, **b)),
            ("+ pipelining (K=4)", sp.Cfg(k=4, pipeline=True, **b)), ("+ free drafts (K=4)", sp.Cfg(k=4, free=True, **b)),
            ("+ compact wire (K=4)", sp.Cfg(k=4, binary=True, **b)), ("Spec+ all lossless", sp.Cfg(**allf, **b)),
            ("Spec+ all + lossy (LOSSY)", sp.Cfg(**allf, lossy=True, **b))]


def fmt(rows: list[dict], cols: list[str]) -> str:
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join(str(r[c]) for c in cols) + " |" for r in rows]
    return "\n".join(out)


def lossless_table() -> list[dict]:
    import test_specplus as T
    n = 20000
    rows = []
    for name, cfg in [("plain chain K=3", sp.Cfg(k=3, max_new=2)),
                      ("tree + adaptive", sp.Cfg(k=3, max_new=2, tree=True, tree_thresh=0.9, adaptive=True)),
                      ("all lossless features", sp.Cfg(k=3, max_new=4, tree=True, tree_thresh=0.9, pipeline=True,
                                                        adaptive=True, binary=True))]:
        rows.append({"setup": name, "draws": n, "TV distance to target": round(T._tv(T._first_two(cfg, n), n), 4)})
    return rows


def main() -> None:
    quick = "--quick" in sys.argv
    tok, model = LlamaCppTokenizer(DRAFT), Model()
    ps = prompts()[: 6 if quick else None]
    items = [(pid, t, tok.encode(chatml(t))) for pid, t in ps]
    rtts = [0.0, 0.05, 0.15, 0.30]
    csv_rows, md_tables = [], {}
    for section, srv in (("ablation", 0.05), ("fast_server", 0.025)):
        rows = []
        for name, cfg in configs(0.15, srv):
            t = time.time()
            st = run(cfg, model, items, sp.Cfg(rtt=0.15, srv_base=srv, max_new=MAX_NEW), cfg is not None and cfg.free)
            r = {"setup": name, **st.row()}
            if cfg is None:
                r.update(rt_per_100="-", alpha="-", tok_per_rt="-", bytes_per_rt="-", passes_per_100=100.0, free_frac="-")
            if cfg and cfg.lossy:
                r["lossy_unchecked_per_100"] = round(100 * st.unchecked / max(st.tokens, 1), 1)
                r["lossy_wrong_per_100"] = round(100 * st.would_reject / max(st.tokens, 1), 2)
            rows.append(r)
            csv_rows.append({"section": section, "rtt_ms": 150, "srv_ms": int(srv * 1000), "tokens": st.tokens, **r})
            print(section, name, r, f"{time.time() - t:.0f}s", flush=True)
            model.save()
        md_tables[section] = rows
    sweep = []
    for rtt in rtts:
        for name, cfg in configs(rtt, 0.05):
            if name not in ("big model alone", "plain spec K=4", "plain spec K=8", "Spec+ all lossless"):
                continue
            st = run(cfg, model, items, sp.Cfg(rtt=rtt, srv_base=0.05, max_new=MAX_NEW), cfg is not None and cfg.free)
            r = {"rtt_ms": int(rtt * 1000), "setup": name, "tok_s": st.row()["tok_s"]}
            sweep.append(r)
            csv_rows.append({"section": "rtt_sweep", "rtt_ms": r["rtt_ms"], "srv_ms": 50, "tokens": st.tokens, "setup": name, **st.row()})
            print("sweep", r, flush=True)
    model.save()
    proof = lossless_table()
    write(md_tables, sweep, proof, items, model, quick)
    keys = sorted({k for r in csv_rows for k in r}, key=lambda k: (k not in ("section", "setup"), k))
    with open(ROOT / "bench/results_specplus.csv", "w", newline="") as f:
        w = csv.DictWriter(f, keys, restval="")
        w.writeheader()
        w.writerows(csv_rows)


def write(tables, sweep, proof, items, model, quick) -> None:
    cols = ["setup", "tok_s", "rt_per_100", "alpha", "tok_per_rt", "bytes_per_rt", "passes_per_100", "free_frac"]
    names = ["big model alone", "plain spec K=4", "plain spec K=8", "Spec+ all lossless"]
    sw = ["| RTT ms | " + " | ".join(names) + " | best Spec+ / best plain |", "|" + "---|" * (len(names) + 2)]
    for rtt in sorted({r["rtt_ms"] for r in sweep}):
        v = {r["setup"]: r["tok_s"] for r in sweep if r["rtt_ms"] == rtt}
        ratio = v["Spec+ all lossless"] / max(v["plain spec K=4"], v["plain spec K=8"])
        sw.append(f"| {rtt} | " + " | ".join(str(v[n]) for n in names) + f" | {ratio:.2f}x |")
    lossy = [r for r in tables["ablation"] if "lossy_unchecked_per_100" in r]
    L = [
        "# Spec+ results", "",
        "## Plain words", "",
        "Plain speculative decoding: a small model on the Mac guesses K tokens. The big model on a far-away GPU checks all K in one pass. "
        "It keeps the guesses that match and adds one token of its own. Each pass costs one network round trip (50 to 300 ms).", "",
        "Spec+ keeps that idea and cuts the cost of the trips: it picks K from the measured network time and hit rate, "
        "sends a small tree instead of one chain where the draft is unsure, drafts the next block while the last one is in flight, "
        "copies free tokens from the prompt or a similar earlier answer, and sends a compact binary message. "
        "Output is still exactly what the big model would write (see the proof below).", "",
        "```mermaid", "flowchart LR",
        "  A[Context] --> B{Free copy found?}", "  B -- yes --> C[Free draft tokens]", "  B -- no --> D[3B drafts block, K from alpha and RTT]",
        "  C --> E[Tree: extra branches where 3B is unsure]", "  D --> E",
        "  E --> F[Binary frame to verifier]", "  F --> G[Big model scores whole tree in one pass]",
        "  F -.while waiting.-> H[Mac drafts next block]",
        "  G --> I[Accept by min 1, p/q; residual on reject]", "  I --> J[Commit tokens + 1 big-model token]",
        "  J --> A", "  H -.keep if all accepted and bonus matches, else drop.-> A", "```", "",
        "## What is real and what is modelled", "",
        f"- **Real:** the Mac Qwen2.5-3B Q4_K_M on llama.cpp (`127.0.0.1:8080`, `n_probs` top-{TOPN}) generates every draft token. Its measured call latency is charged to a virtual clock. {model.calls} real llama calls were made in this run (the rest came from the memo of earlier calls).",
        "- **Stand-in target, not a real big model:** no Qwen-vocabulary verifier that returns full distributions was reachable. `bench/results_modal.md` and `bench/spec_results.md` did not exist, and the Modal app serves Qwen3.5-122B, whose vocabulary differs from Qwen2.5-3B. So the target is the same 3B with its distribution sharpened (temperature 0.6, top-16). Acceptance rate alpha therefore reflects that stand-in, not a real 30B or 122B.",
        "- **Modelled:** network round trip (RTT) and verifier compute. Verify pass = server base time + 0.5 ms per tree node. Big model alone = one streamed request: one RTT, then one server step per token. Server step is 50 ms (20 tok/s, a V100 class box with CPU offload) in the main table and 25 ms in the fast-server table.",
        f"- {len(items)} prompts ({', '.join(str(i[0]) for i in items)}), {MAX_NEW} new tokens each, one run per setup, sampled output (noisy). Mix: 5 code edits, 3 math, 2 chat, 3 code writing, 4 short factual (two paraphrase pairs for the cache-neighbour draft).",
        "- Quick mode used." if quick else "",
        "- Plain spec here uses the same exact verify code (residual correction) with a chain of fixed K and the old JSON protocol, so the comparison isolates the Spec+ features. The older `SpecVerifierBackend` path samples its correction from the target instead of the residual.", "",
        "Columns: `tok_s` virtual-clock tokens/s; `rt_per_100` round trips per 100 tokens; `alpha` accepted / (accepted + rejections); `tok_per_rt` tokens committed per round trip; `bytes_per_rt` up + down; `passes_per_100` big-model forward passes per 100 tokens (100 when it decodes alone); `free_frac` share of sent draft tokens that cost no draft-model call.", "",
        "## Ablation (RTT 150 ms, server step 50 ms)", "", fmt(tables["ablation"], cols), "",
        "## Same table, fast server (25 ms per step)", "", fmt(tables["fast_server"], cols), "",
        "## RTT sweep (tokens/s, server step 50 ms)", "", "\n".join(sw), "",
        "## Lossy mode (off by default)", "",
        "Accepts any token with draft probability above 0.98 without testing it. " +
        (fmt(lossy, ["setup", "tok_s", "lossy_unchecked_per_100", "lossy_wrong_per_100"]) if lossy else ""), "",
        "`lossy_wrong_per_100` is the summed probability, per 100 tokens, that the big model would have rejected the unchecked tokens. It is a measure of expected tokens that differ from the big model's output.", "",
        "## Lossless proof", "",
        "Toy Markov model, 5 tokens, draft and target differ. We generate the first two tokens many times and compare the empirical joint distribution with the exact target joint. TV = total variation distance. Sampling noise floor for 25 cells and 20,000 draws is about 0.01. Control: replacing the residual by a plain target sample on rejection gives TV 0.24.", "",
        fmt(proof, ["setup", "draws", "TV distance to target"]), "",
        "Also covered by `tests/test_specplus.py::test_lossless_output_distribution_matches_target`. Multiple children per node are drawn without replacement; after a reject the target is replaced by norm(max(r - q, 0)) and the rejected token is removed from q.", "",
        "## Reproduce", "", "```", "bench/serve_local.sh &", ".venv/bin/python bench/run_specplus.py", "```", "",
        "## Verdict", "", "VERDICT_PLACEHOLDER", ""]
    (ROOT / "bench/results_specplus.md").write_text("\n".join(L))


if __name__ == "__main__":
    main()
