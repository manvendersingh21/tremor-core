"""N+1 measurement: the 30B with and without memory filled by the big model.

    .venv/bin/python bench/memory/run_memory.py all            # every stage, resumable
    .venv/bin/python bench/memory/run_memory.py <stage>        # split base top teacher extract eval real report

Needs: the GPU port forward on $GPU_PORT (default 11444, Ollama qwen3:30b-instruct), CRUSOE_API_KEY, MiniLM.
The `real` stage also needs CHIMERA_GRAPH_URL (Neo4j) and CHIMERA_DB_URL (Supabase). Rows are cached under
bench/.scratch/memory/ so a rerun skips finished work. Temperature 0 and a fixed seed on the 30B. Keys are never written.
"""
from __future__ import annotations

import concurrent.futures as cf
import csv
import json
import os
import pathlib
import random
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "bench", ROOT / "bench" / "datasets"):
    sys.path.insert(0, str(p))
import conftest  # noqa: E402,F401
import grade  # noqa: E402
from run_bench import load_env  # noqa: E402

load_env()
from chimera_core.ladder import TopBackend  # noqa: E402
from chimera_core.memory import InMemoryStore, Memory, llm_extractor  # noqa: E402
from chimera_core.memory.extract import PROMPT as EXTRACT_PROMPT  # noqa: E402,F401

STORE = ROOT / "bench/.scratch/memory"  # inside the repo (git-ignored): survives a gateway restart
STORE.mkdir(parents=True, exist_ok=True)
OUT_MD, OUT_CSV = ROOT / "bench/results_memory.md", ROOT / "bench/results_memory.csv"
GPU = f"http://127.0.0.1:{os.environ.get('GPU_PORT', '11444')}"
TOP_MODEL = "deepseek-ai/DeepSeek-V4.1-Flash"
PRICE_TOP = (0.29, 0.007, 1.20)  # $ per 1M tokens: input, cached input, output (Crusoe list)
MAX_TOKENS = 1536
N_TEST, N_TRAIN_MAX, SIZES, SEED = int(os.environ.get("N_TEST", 80)), 260, [25, 50, 100, 200], 7
TENANT = "bench-n1"
W30 = int(os.environ.get("W30", 4))  # the shared Ollama box answers parallel requests in the same wait as one


def jl_read(name: str) -> list[dict]:
    f = STORE / name
    return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


def jl_append(name: str, rec: dict) -> None:
    with (STORE / name).open("a") as fh:
        fh.write(json.dumps(rec) + "\n")


def top_cost(tin: int, tout: int, cached: int = 0) -> float:
    return ((tin - cached) * PRICE_TOP[0] + cached * PRICE_TOP[1] + tout * PRICE_TOP[2]) / 1e6


# ---- models ------------------------------------------------------------------------------------------------
def call30(prompt: str, max_tokens: int = MAX_TOKENS) -> tuple[str, int, int]:
    body = json.dumps({"model": "qwen3:30b-instruct", "stream": False, "think": False,
                       "options": {"num_predict": max_tokens, "temperature": 0, "seed": 1},
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    for attempt in range(2):
        try:
            req = urllib.request.Request(GPU + "/api/chat", body, {"Content-Type": "application/json"})
            d = json.load(urllib.request.urlopen(req, timeout=300))
            text = (d.get("message") or {}).get("content") or ""
            return text.split("</think>")[-1].strip(), d.get("prompt_eval_count", 0), d.get("eval_count", 0)
        except Exception:  # noqa: BLE001
            if attempt:
                raise
            time.sleep(3)
    raise RuntimeError


_top = None


def call_top(prompt: str) -> tuple[str, dict]:
    global _top
    if _top is None:
        _top = TopBackend(TOP_MODEL, {"thinking": False}, api_key=os.environ["CRUSOE_API_KEY"],
                          base_url="https://api.inference.crusoecloud.com", timeout=300)
    for attempt in range(3):
        try:
            b = TopBackend(TOP_MODEL, {"thinking": False}, api_key=os.environ["CRUSOE_API_KEY"],
                           base_url="https://api.inference.crusoecloud.com", timeout=300)
            t = b.complete(prompt, MAX_TOKENS)
            return t, b.last_usage
        except Exception:  # noqa: BLE001
            if attempt == 2:
                raise
            time.sleep(4)
    raise RuntimeError


# ---- data --------------------------------------------------------------------------------------------------
def family(r: dict) -> str:
    import re
    return re.sub(r"-\d+$", "", r["id"]) if r["id"].startswith("triv-") or r.get("source") == "custom" else r["id"]


def load_tasks() -> list[dict]:
    seen, rows = set(), []
    for f in (ROOT / "bench/datasets/suite.jsonl", ROOT / "bench/cost_case/tasks.jsonl"):
        for x in f.read_text().splitlines():
            r = json.loads(x)
            if r.get("grader") != "unit_test" or r["prompt"] in seen:
                continue
            seen.add(r["prompt"])
            r.setdefault("difficulty", "hard" if r.get("type") == "hard" else "everyday")
            rows.append(r)
    return rows


def stage_split() -> tuple[list[dict], list[dict]]:
    f = STORE / "split.json"
    rows = {r["id"]: r for r in load_tasks()}
    if f.exists():
        d = json.loads(f.read_text())
        return [rows[i] for i in d["test"]], [rows[i] for i in d["train"]]
    rng = random.Random(SEED)
    ids = sorted(rows)
    rng.shuffle(ids)
    hard = [i for i in ids if rows[i]["difficulty"] in ("everyday", "hard")]  # trivial items leave no headroom
    test = hard[:N_TEST]
    # whole families stay on one side only when the family has a single member; near-duplicate families can span
    # both sides on purpose (same concept, different problem), but no problem is on both sides.
    tset = set(test)
    train = [i for i in ids if i not in tset][:N_TRAIN_MAX]
    assert not tset & set(train) and not {rows[i]["prompt"] for i in tset} & {rows[i]["prompt"] for i in train}
    f.write_text(json.dumps({"test": test, "train": train}))
    print(f"split: test {len(test)}, train stream {len(train)}; total unit-test tasks {len(rows)}", flush=True)
    return [rows[i] for i in test], [rows[i] for i in train]


# ---- stages ------------------------------------------------------------------------------------------------
def run_rows(name: str, rows: list[dict], fn, workers: int = 1) -> list[dict]:
    done = {r["id"]: r for r in jl_read(name)}
    todo = [r for r in rows if r["id"] not in done]

    def one(r):
        t0 = time.perf_counter()
        try:
            rec = fn(r)
        except Exception as e:  # noqa: BLE001
            rec = {"text": "", "pass": 0, "error": f"{type(e).__name__}: {str(e)[:100]}"}
        rec.update(id=r["id"], ms=round((time.perf_counter() - t0) * 1000))
        return rec

    with cf.ThreadPoolExecutor(workers) as ex:
        for rec in ex.map(one, todo):
            jl_append(name, rec)
            print(name, rec["id"], rec.get("pass"), rec.get("tin"), rec.get("tout"), rec.get("error", ""), flush=True)
            done[rec["id"]] = rec
    return [done[r["id"]] for r in rows if r["id"] in done]


def f30(prefix_of=None):
    def fn(r):
        pre = prefix_of(r) if prefix_of else ""
        text, tin, tout = call30((pre + "\n\n" if pre else "") + r["prompt"])
        return {"text": text, "pass": grade.grade(r, text) or 0, "tin": tin, "tout": tout, "ctx_chars": len(pre)}
    return fn


def ftop(r):
    text, u = call_top(r["prompt"])
    tin, tout, c = u["prompt_tokens"], u["completion_tokens"], u["cached_tokens"]
    return {"text": text, "pass": grade.grade(r, text) or 0, "tin": tin, "tout": tout, "cached": c,
            "usd": top_cost(tin, tout, c)}


def teacher_rows(train: list[dict]) -> list[dict]:
    """Train stream rows the big model solved (tests passed), in stream order, first 200."""
    got = {r["id"]: r for r in jl_read("teacher.jsonl")}
    return [dict(got[r["id"]], row=r) for r in train if r["id"] in got and got[r["id"]]["pass"] == 1]


def get_embedder():
    from chimera_core.cache.semantic_cache import OnnxMiniLMEmbedder
    return OnnxMiniLMEmbedder()


def extraction(ok: list[dict]) -> dict[str, tuple]:
    """One 30B call per stored solution: concepts + why. Cached, so every curve size reuses it."""
    ext = {r["id"]: r for r in jl_read("extract.jsonl")}

    def one(t):
        t0 = time.perf_counter()
        text, tin, tout = call30(EXTRACT_PROMPT.format(problem=t["row"]["prompt"][:1500], solution=t["text"][:2500]), 300)
        return {"id": t["id"], "text": text, "tin": tin, "tout": tout, "ms": round((time.perf_counter() - t0) * 1000)}

    with cf.ThreadPoolExecutor(W30) as ex:
        for rec in ex.map(one, [t for t in ok if t["id"] not in ext]):
            jl_append("extract.jsonl", rec)
            ext[rec["id"]] = rec
            print("extract", rec["id"], rec["tin"], rec["tout"], flush=True)
    return ext


def build_memory(ok: list[dict], ext: dict, n: int, embedder, store=None, tenant=TENANT) -> Memory:
    by_prompt = {t["row"]["prompt"]: ext[t["id"]]["text"] for t in ok}
    lookup = lambda p, s: llm_extractor(lambda _q: by_prompt[p])(p, s)  # noqa: E731  replay the cached 30B answer
    m = Memory(store or InMemoryStore(), embedder, tenant, extractor=lookup)
    for t in ok[:n]:
        m.store(t["row"]["prompt"], t["text"], TOP_MODEL, "top", True, True, {"in": t["tin"], "out": t["tout"]})
    return m


def stage_eval(test, ok, ext, embedder) -> None:
    class Cache:  # embeddings are the slow part on the Mac; memoise per text
        def __init__(s, e): s.e, s.m = e, {}
        def embed(s, t):
            if t not in s.m: s.m[t] = s.e.embed(t)
            return s.m[t]
    emb = Cache(embedder)
    sizes = [n for n in SIZES if n <= len(ok)] + ([len(ok)] if len(ok) not in SIZES and len(ok) < SIZES[-1] else [])
    for n in sizes:
        m = build_memory(ok, ext, n, emb)
        ctx = {r["id"]: m.retrieve(r["prompt"]).render() for r in test}
        run_rows(f"with_mem_{n}.jsonl", test, f30(lambda r, c=ctx: c[r["id"]]), W30)
    # control: same size as the largest memory, but 3 RANDOM stored solutions instead of similar ones
    nmax = sizes[-1]
    m = build_memory(ok, ext, nmax, emb)
    from chimera_core.memory.memory import Example, MemoryContext
    pool = list(m.graph.neighbors(TENANT, [n for n in range(1, 4 * nmax + 10)]))
    sol_edge = [(e, a, b) for e, a, b in pool if e.rel == "solves"]
    why = {b.id: a.text for e, a, b in pool if e.rel == "part_of"}
    rng = random.Random(SEED)

    def rand_ctx(r):
        pick = rng.sample(sol_edge, 3)
        return MemoryContext([Example(b.text, a.text, why.get(a.id, "")) for _, a, b in pick]).render()
    ctx = {r["id"]: rand_ctx(r) for r in test}
    run_rows("control_random.jsonl", test, f30(lambda r: ctx[r["id"]]), W30)
    # similar-only retrieval with the graph hop switched off would need another run; not part of this contract.
    (STORE / "ctx_sizes.json").write_text(json.dumps({"sizes": sizes}))


def stage_real(test, ok, ext, embedder) -> dict:
    """Write the real stores (teacher pairs in Supabase, graph in Neo4j) and check they agree with the in-memory run."""
    from chimera_core.memory import default_store
    store = default_store()
    mem = Memory(store, embedder, TENANT, extractor=lambda p, s: llm_extractor(
        lambda _q, d={t["row"]["prompt"]: ext[t["id"]]["text"] for t in ok}: d[p])(p, s))
    mem.purge()
    t0 = time.time()
    for t in ok[:200]:
        mem.store(t["row"]["prompt"], t["text"], TOP_MODEL, "top", True, True, {"in": t["tin"], "out": t["tout"]})
    st = mem.stats()
    local = build_memory(ok, ext, 200, embedder)
    agree = 0
    for r in test[:20]:
        a = [e.problem for e in mem.retrieve(r["prompt"]).examples]
        b = [e.problem for e in local.retrieve(r["prompt"]).examples]
        agree += bool(a) and a[:1] == b[:1]
    res = {"stats": st, "store": type(store).__name__, "top1_agree_of_20": agree, "seconds": round(time.time() - t0)}
    (STORE / "real.json").write_text(json.dumps(res))
    print("real", res, flush=True)
    return res


def main() -> None:
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"
    run = (lambda s: stage in ("all", s))
    test, train = stage_split()
    if stage == "split":
        return print("split ok")
    if run("base"):
        run_rows("baseline30.jsonl", test, f30(), W30)
    if run("top"):
        run_rows("top_test.jsonl", test, ftop, 4)
    if run("teacher"):
        run_rows("teacher.jsonl", train, ftop, 4)
    ok = teacher_rows(train)
    print(f"teacher solved {len(ok)} of {len(train)}", flush=True)
    if run("extract") or run("eval") or run("real"):
        ok = ok[:200]
        ext = extraction(ok)
    if run("eval"):
        stage_eval(test, ok, ext, get_embedder())
    if run("real") and os.environ.get("CHIMERA_GRAPH_URL"):
        stage_real(test, ok, ext, get_embedder())
    if run("report"):
        import report
        report.write(test, train, ok)


if __name__ == "__main__":
    main()
