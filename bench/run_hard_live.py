"""Live finding on moderately-hard coding questions: 30B alone vs the ladder vs the 763B alone (bench/results_hard_live.md).

    PLAIN (A): every question to the self-hosted 30B alone (qwen3:30b-instruct on GPU 1 of the A6000 box).
    POOL  (B): the deployed order: solved-problem bank (Supabase `solved_bank`, served only if the stored answer passes
               this question's tests) -> shared cache (Supabase `prompts`: exact hash, then cosine 0.97 + guard,
               300 ms budget, settings from [cache] in chimera.toml) -> 30B (confidence gate 0.95; prompts above
               complexity 0.6 go straight to the 763B) -> the 30B answer runs its tests, a failure climbs to the
               Crusoe 763B. Only answers that pass their tests are written to the cache and the bank.
    TOP   (C): every question to the Crusoe 763B alone.
    WARM     : POOL again on the bank and cache POOL filled (repeat traffic); checks live reads.

Every model call goes through SpeculativeCascadeRouter.generate(). The 30B is served by bench/a6000/serve.sh, started
by bench/a6000/watchdog.sh with ONLY_GPUS=1 (yields to anyone within ~10 s). Uses run_a6000.py for the box.

    .venv/bin/python bench/run_hard_live.py build            # bench/hard_live/questions.jsonl
    .venv/bin/python bench/run_hard_live.py run PLAIN POOL TOP WARM
    .venv/bin/python bench/run_hard_live.py store            # live store check (counts, regrade stored rows, latency)
    .venv/bin/python bench/run_hard_live.py tables           # numbers for the report

Rows: bench/.scratch/hard_live/<MODE>.jsonl, one per question; a rerun skips finished ids. A row cut by a GPU yield
is dropped and redone, so a yield never becomes a 763B call.
"""
from __future__ import annotations

import collections
import concurrent.futures as cf
import functools
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench"))
sys.path.insert(0, str(ROOT / "bench" / "hard_live"))
import run_a6000 as A  # noqa: E402  (sets up chimera_core and the graders)
from run_a6000 import grade  # noqa: E402
from chimera_core import RouterConfig, SpeculativeCascadeRouter  # noqa: E402
from chimera_core.cache.guard import make_guard  # noqa: E402
from chimera_core.cache.pgvector_cache import PgStore, PgVectorCache  # noqa: E402
from chimera_core.config import load_config  # noqa: E402
from chimera_core.inference.local_draft import LlamaCppBackend  # noqa: E402
from chimera_core.memory import Bank, PgBankStore  # noqa: E402
from chimera_core.memory.bank import prompt_hash as bank_hash  # noqa: E402
from chimera_core.memory.safety import scrub  # noqa: E402
from chimera_core.router import complexity_score  # noqa: E402
from chimera_core.tiers import TierPool  # noqa: E402
from run_bench import load_env  # noqa: E402

import classics  # noqa: E402
import summary  # noqa: E402

Q = ROOT / "bench/hard_live/questions.jsonl"
STORE = ROOT / "bench/.scratch/hard_live"
TENANT = "bench-hard-live"
GPU, TOP, MODEL = A.GPU, A.TOP, "qwen3:30b-instruct"
SUITE_EXTRA = ["humaneval-128", "humaneval-163", "humaneval-77", "mbpp-228", "mbpp-235", "mbpp-286", "mbpp-301"]


# ---------------------------------------------------------------- the question set ----
def build() -> None:
    """~40 questions: (1) cost-case HARD tasks the 30B failed in at least 1 of 3 earlier plain runs
    (bench/.scratch/a6000), (2) harder HumanEval/MBPP suite items it failed the same way, (3) the classics, (4) six
    HARD tasks it passed every time (controls: the ladder should not climb on them). Items that every earlier ladder
    repeat also failed (tests that ask for an unstated format) are left out."""
    S = ROOT / "bench/.scratch/a6000"

    def fails(data: str, mode: str, reps) -> collections.Counter:
        c: collections.Counter = collections.Counter()
        for r in reps:
            for x in map(json.loads, (S / f"qwen_{mode}_{data}_r{r}.jsonl").read_text().splitlines()):
                c[x["id"]] += x["grade"] != 1
        return c

    cost = {r["id"]: r for r in map(json.loads, (ROOT / "bench/cost_case/tasks.jsonl").read_text().splitlines())}
    suite = {r["id"]: r for r in map(json.loads, (ROOT / "bench/datasets/suite.jsonl").read_text().splitlines())}
    pf, lf = fails("cost", "PLAIN", (1, 2, 3)), fails("cost", "POOL", (1, 2, 3, 4))
    hard = sorted(i for i, r in cost.items() if r["difficulty"] == "hard")
    picked = [dict(cost[i], pick="cost-case hard, 30B failed before") for i in hard if pf[i] and lf[i] < 4]
    spf, slf = fails("suite", "PLAIN", (1, 2, 3)), fails("suite", "POOL", (1, 2, 3, 4))
    for i in SUITE_EXTRA:
        assert spf[i] and slf[i] < 4, i
        picked.append(dict(suite[i], id="suite-" + i, difficulty="hard", pick="suite HumanEval/MBPP, 30B failed before"))
    picked += [dict(q, pick="classic") for q in classics.CLASSICS]
    ok = [i for i in hard if not pf[i] and not lf[i]]
    picked += [dict(cost[ok[int(k * len(ok) / 6)]], pick="control: cost-case hard, 30B passed before") for k in range(6)]
    Q.write_text("".join(json.dumps(q) + "\n" for q in picked))
    print(len(picked), "questions ->", Q.relative_to(ROOT), collections.Counter(q["pick"] for q in picked))


def questions() -> list[dict]:
    return [json.loads(x) for x in Q.read_text().splitlines()]


def passes(row: dict, answer: str) -> bool:
    return bool(answer) and grade.grade(row, answer) == 1


# ---------------------------------------------------------------- live runs ----
class Run:
    def __init__(self, mode: str, emb) -> None:
        self.mode, self.emb = mode, emb
        self.out = STORE / f"{mode}.jsonl"
        self.cache = self.bank = None
        if mode in ("POOL", "WARM"):
            cc = load_config(ROOT / "chimera.toml").cache  # the deployed cache settings; tenant is ours
            dsn = os.environ["CHIMERA_DB_URL"]
            self.cache = PgVectorCache(emb, lambda: PgStore(dsn, max_size=1), threshold=0.97, tenant=TENANT,
                                       store_text=True, guard=make_guard(), budget_s=cc.budget_ms / 1000,
                                       normalize=cc.normalize, top_k=cc.top_k)
            self.bank = Bank(PgBankStore(dsn, max_size=1), emb, TENANT, verify=lambda a, t: bool(grade.unit_test(t, a)))
        self.routers: dict[str, tuple] = {}
        self.top = self._router(TierPool([TOP], min_confidence=0.95, max_tokens=1024), shared=self.cache)

    def _router(self, pool: TierPool, shared=None) -> tuple:
        last: dict = {}
        orig = pool.generate

        def spy(*a, **kw):
            last["r"] = r = orig(*a, **kw)
            return r
        pool.generate = spy
        return SpeculativeCascadeRouter(LlamaCppBackend(), exact=False, shared=shared,
                                        embedder=self.emb if shared is not None else None,
                                        config=RouterConfig(min_confidence=0.95), pool=pool), last

    def router(self, url: str) -> tuple:
        if url not in self.routers:
            g = A.gpu_tier("qwen", url, self.mode == "PLAIN")
            tiers = [g] if self.mode == "PLAIN" else [g, TOP]
            self.routers[url] = self._router(TierPool(tiers, min_confidence=0.95, max_tokens=1024), shared=self.cache)
        return self.routers[url]

    def wait_gpu(self) -> str:
        fresh = False
        while True:
            urls = A.cached_endpoints(force=fresh)
            fresh = True
            for u in urls:
                if A.loaded(u, MODEL):
                    return u
                if A.up(u):
                    try:
                        A.raw_generate(u, MODEL, "hello", 2)  # cold load after a (re)start; not timed
                    except Exception:  # noqa: BLE001
                        pass
                    if A.loaded(u, MODEL):
                        return u
            print(self.mode, "waiting for GPU 1", flush=True)
            time.sleep(15)

    def one(self, row: dict, url: str | None) -> dict | None:
        prompt, t0 = row["prompt"], time.perf_counter()
        text, tier, per, attempts, err, climbed = "", "", {}, [], "", False
        store: dict = {}
        try:
            if self.bank is not None:  # deployed order: the bank comes before any cache or model call
                tb = time.perf_counter()
                lk = self.bank.lookup(prompt, tests=row["data"])
                store["bank_read_ms"] = round((time.perf_counter() - tb) * 1000, 1)
                store["bank"] = lk.kind
                if lk.kind == "served":
                    text, tier = lk.answer, "bank"
            if not tier:
                router, last = self.top if self.mode == "TOP" else self.router(url)
                last.clear()
                check = (lambda a: passes(row, a)) if self.cache is not None else None
                res = router.generate(prompt, check=check)
                if self.cache is not None:
                    self.cache.flush()
                ev = next((e for e in reversed(res.telemetry.events) if e["step"] == "cache_shared"), None)
                if ev:
                    store.update(cache_read_ms=ev.get("ms"), cache_status=ev.get("status"), cache_score=ev.get("score"))
                r = last.get("r")
                text, tier = res.text, (r.tier if r else res.telemetry.tier_used)
                per = {k: v.model_dump() for k, v in r.per_tier.items()} if r else {}
                attempts = list(r.attempts) if r else []
                if check is not None and tier == GPU and not check(text):  # failed tests: climb one tier
                    trouter, tlast = self.top
                    tlast.clear()
                    res2 = trouter.generate(prompt, check=check)
                    self.cache.flush()
                    r2 = tlast.get("r")
                    if r2 is not None:
                        text, tier, climbed = res2.text, r2.tier, True
                        attempts += list(r2.attempts)
                        for k, v in r2.per_tier.items():
                            per[k] = v.model_dump()
            if self.bank is not None and tier in (GPU, TOP.name) and passes(row, text):
                tw = time.perf_counter()
                store["bank_write_id"] = self.bank.add(prompt, text, row["data"], source="hard-live", model=tier, tier=tier,
                                                       tokens={"in": per.get(tier, {}).get("tokens_in", 0),
                                                               "out": per.get(tier, {}).get("tokens_out", 0)})
                store["bank_write_ms"] = round((time.perf_counter() - tw) * 1000, 1)
        except Exception as e:  # noqa: BLE001  AllTiersFailed or a tier error that escaped
            text, tier, err = "", "failed", f"{type(e).__name__}: {e}"[:200]
        ms = (time.perf_counter() - t0) * 1000
        if url is not None and tier not in ("bank", "exact_cache", "semantic_cache"):
            gpu_should = self.mode == "PLAIN" or complexity_score(prompt) <= A.gpu_tier("qwen", url, False).max_complexity
            gpu_err = per.get(GPU, {}).get("errors", 0) > 0 or (gpu_should and GPU not in attempts)
            if (gpu_err or tier == "failed") and not (A.up(url) and A.loaded(url, MODEL)):
                for router, _ in self.routers.values():  # a yield: forget the dead tier, redo the row later
                    for d in (router.pool._health, router.pool._fails, router.pool._open_until, router.pool._backends):
                        d.clear()
                return None
        return {"id": row["id"], "mode": self.mode, "tier": tier, "climbed": climbed, "latency_ms": round(ms),
                "complexity": round(complexity_score(prompt), 3), "attempts": attempts, "per_tier": per, "store": store,
                "error": err, "answer": text, "grade": int(passes(row, text)), "at": time.time()}

    def run(self) -> str:
        qs = questions()
        if self.mode == "WARM":  # starts once POOL has every row, on the bank and cache POOL filled
            pool = STORE / "POOL.jsonl"
            while not (pool.exists() and {q["id"] for q in qs} <= {json.loads(x)["id"] for x in pool.read_text().splitlines()}):
                time.sleep(20)
        done = {json.loads(x)["id"] for x in self.out.read_text().splitlines()} if self.out.exists() else set()
        if self.mode == "POOL" and not done:  # a fresh tenant: the first pass starts from an empty bank and cache
            counts("before POOL purge")
            print("purged cache", self.cache.purge(), "bank", self.bank.purge(), flush=True)
            counts("POOL start")
        t0 = time.time()
        with self.out.open("a") as fh:
            for row in qs:
                if row["id"] in done:
                    continue
                while True:
                    rec = self.one(row, None if self.mode == "TOP" else self.wait_gpu())
                    if rec is not None:
                        break
                    print(self.mode, row["id"], "dropped (GPU went away), redo", flush=True)
                fh.write(json.dumps(rec) + "\n")
                fh.flush()
                print(self.mode, row["id"], rec["tier"], "climbed" if rec["climbed"] else "", rec["latency_ms"],
                      rec["grade"], rec["error"], flush=True)
        if self.mode in ("POOL", "WARM"):
            counts(f"{self.mode} end")
        return f"{self.mode} finished in {time.time() - t0:.0f} s"


@functools.lru_cache(None)
def _db() -> PgStore:  # one connection for the counts; Supabase's session pooler allows 15 clients in all
    return PgStore(os.environ["CHIMERA_DB_URL"], max_size=1)


def counts(label: str) -> dict:
    """Rows of our tenant in the live cache (`prompts`) and bank (`solved_bank`) tables; appended to store.jsonl."""
    db = _db()
    c = db._tx(TENANT, "select count(*), count(*) filter (where verified) from prompts where tenant=%s", (TENANT,), "one")
    b = db._tx(TENANT, "select count(*), coalesce(sum(hits), 0) from solved_bank where tenant=%s", (TENANT,), "one")
    out = {"label": label, "at": time.time(), "cache_rows": c[0], "cache_verified": c[1], "bank_rows": b[0], "bank_hits": int(b[1])}
    with (STORE / "store.jsonl").open("a") as fh:
        fh.write(json.dumps(out) + "\n")
    print("store", out, flush=True)
    return out


def store_check() -> None:
    """Read back every row we wrote, regrade it against its question's tests, and time live reads. Then purge."""
    load_env()
    qs = {scrub(q["prompt"]): q for q in questions()}
    db = _db()
    rows = db._tx(TENANT, "select prompt_text, answer, verified, tier from prompts where tenant=%s", (TENANT,), "all")
    bank = db._tx(TENANT, "select prompt, answer, tier from solved_bank where tenant=%s", (TENANT,), "all")
    regrade = {"cache": [sum(passes(qs[p], a) for p, a, *_ in rows if p in qs), len(rows), sum(not v for _, _, v, _ in rows),
                         sum(p not in qs for p, *_ in rows)],
               "bank": [sum(passes(qs[p], a) for p, a, _ in bank if p in qs), len(bank), 0, sum(p not in qs for p, *_ in bank)]}
    emb = A.LockedEmbedder()
    run = Run("WARM", emb)
    lat: dict[str, list] = {"cache_read": [], "bank_read": [], "ping": []}
    hits = collections.Counter()
    for q in qs.values():
        t = time.perf_counter()
        lk = run.cache.lookup(q["prompt"])
        lat["cache_read"].append((time.perf_counter() - t) * 1000)
        hits["cache_" + ("hit" if lk.hit else lk.status or "miss")] += 1
        t = time.perf_counter()
        bl = run.bank.store.exact(TENANT, bank_hash(scrub(q["prompt"])))
        lat["bank_read"].append((time.perf_counter() - t) * 1000)
        hits["bank_" + ("hit" if bl else "miss")] += 1
        lat["ping"].append(run.cache.ping())  # one bare DB round trip, ms
    out = {"regrade [passing, rows, unverified, unknown prompt]": regrade, "probe_hits": dict(hits),
           **{f"{k}_p50_ms": round(summary.pct(v, 0.5), 1) for k, v in lat.items()},
           **{f"{k}_p90_ms": round(summary.pct(v, 0.9), 1) for k, v in lat.items()}}
    (STORE / "store_check.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
    counts("after store check, before purge")
    print("purged cache", run.cache.purge(), "bank", run.bank.purge(), flush=True)
    counts("after purge")


def run(modes: list[str]) -> None:
    load_env()
    STORE.mkdir(parents=True, exist_ok=True)
    emb = A.LockedEmbedder()
    emb.embed("warm up")
    runs = [Run(m, emb) for m in modes]
    with cf.ThreadPoolExecutor(len(runs)) as ex:
        for f in cf.as_completed([ex.submit(r.run) for r in runs]):
            print(f.result(), flush=True)


# ---------------------------------------------------------------- numbers ----
def tables() -> None:
    qs = questions()
    rows = {m: [json.loads(x) for x in (STORE / f"{m}.jsonl").read_text().splitlines()]
            for m in ("PLAIN", "POOL", "TOP", "WARM") if (STORE / f"{m}.jsonl").exists()}
    out = {}
    for m, rs in rows.items():
        top = [r["per_tier"].get(TOP.name, {}) for r in rs]
        gpu = [r["per_tier"].get(GPU, {}) for r in rs]
        lat = [r["latency_ms"] for r in rs]
        out[m] = {"n": len(rs), "solved": sum(r["grade"] for r in rs), "wrong_served": sum(r["grade"] != 1 for r in rs),
                  "answered_by": dict(collections.Counter(r["tier"] + ("+climb" if r["climbed"] else "") for r in rs)),
                  "top_calls": sum(t.get("calls", 0) for t in top), "top_tokens_in": sum(t.get("tokens_in", 0) for t in top),
                  "top_tokens_out": sum(t.get("tokens_out", 0) for t in top),
                  "top_dollars": round(sum(t.get("dollars", 0.0) for t in top), 6),
                  "gpu_calls": sum(g.get("calls", 0) for g in gpu), "gpu_tokens": sum(g.get("tokens_in", 0) + g.get("tokens_out", 0) for g in gpu),
                  "p50_ms": summary.pct(lat, 0.5), "p90_ms": summary.pct(lat, 0.9),
                  "errors": sum(bool(r["error"]) for r in rs)}
    if "PLAIN" in rows and "POOL" in rows:
        out["recovery"] = summary.recovery(qs, rows["PLAIN"], rows["POOL"])
    by = {m: {r["id"]: r for r in rs} for m, rs in rows.items()}
    out["per_question"] = {q["id"]: {m: (by[m][q["id"]]["grade"], by[m][q["id"]]["tier"] + ("+climb" if by[m][q["id"]]["climbed"] else ""))
                                     for m in by if q["id"] in by[m]} for q in qs}
    (STORE / "tables.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "per_question"}, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1]
    {"build": lambda: build(), "run": lambda: run(sys.argv[2:]), "store": store_check, "tables": tables}[cmd]()
