"""--live: run each logged request through the real ladder, then grade a sample against the 763B with a cheap GMI judge.

Ladder = SpeculativeCascadeRouter.generate() with a TierPool: Supabase cache (exact, cosine 0.97 + guard) -> Akash 30B -> Crusoe 763B.
Reference = a second router with only the 763B and no cache, also through generate(). Judge = GMI chat model, grader only.
Cache tenant is private to the run and purged before and after. Records are appended to a JSONL so a rerun resumes.
"""
from __future__ import annotations

import json
import os
import pathlib
import random
import re
import time

from . import prices
from .estimate import kind
from .logs import Req, est_tokens

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRATCH = ROOT / "bench" / ".scratch"  # evallog.py reads replay_eval_log.jsonl from here
EVAL_LOG = SCRATCH / "replay_eval_log.jsonl"
TOP_MODEL = "deepseek-ai/DeepSeek-V4.1-Flash"
JUDGE_MODEL = "zai-org/GLM-5.3-Flash"
GMI = "https://api.gmi-serving.com"
PASS_SCORE = 4  # judge 1-5; the 30B answer passes at >= 4 against the 763B answer
YESNO = ("Question:\n{q}\n\nAnswer:\n{a}\n\nDoes the answer correctly and fully answer this exact question? Reply with only YES or NO.")


def _tiers():
    from chimera_core.tiers import TierCfg
    top = TierCfg(name="cloud-deepseek", device="cloud", backend="openai", url="https://api.inference.crusoecloud.com",
                  model=TOP_MODEL, family="deepseek", cost_per_1k_in=prices.TOP[0] / 1000, cost_per_1k_out=prices.TOP[1] / 1000,
                  timeout_s=240, template_kwargs={"thinking": False})
    small = TierCfg(name="gpu-small", device="gpu", backend="ollama", url=os.environ.get("CHIMERA_GPU_URL", ""),
                    model="qwen3:30b-instruct", family="qwen", max_complexity=0.6, timeout_s=180)
    return small, top


def build(tenant: str):
    """(ladder router, reference router). Neither starts the Mac 3B (the llama.cpp object is only the router's unused local slot)."""
    from chimera_core import RouterConfig, SpeculativeCascadeRouter
    from chimera_core.cache.guard import make_guard
    from chimera_core.cache.pgvector_cache import PgStore, PgVectorCache
    from chimera_core.cache.semantic_cache import CachedEmbedder, OnnxMiniLMEmbedder
    from chimera_core.inference.local_draft import LlamaCppBackend
    from chimera_core.tiers import TierPool
    small, top = _tiers()
    emb = CachedEmbedder(OnnxMiniLMEmbedder())
    emb.embed("warm up")
    dsn = os.environ["CHIMERA_DB_URL"]
    shared = PgVectorCache(emb, lambda: PgStore(dsn), threshold=0.97, tenant=tenant, store_text=True, guard=make_guard(),
                           budget_s=3.0, cooldown_s=0.0, max_strikes=10**9)
    cfg = RouterConfig(min_confidence=0.95)
    ladder = SpeculativeCascadeRouter(LlamaCppBackend(), exact=False, shared=shared, embedder=emb, config=cfg,
                                      pool=TierPool([small, top], min_confidence=0.95, max_tokens=1024))
    ref = SpeculativeCascadeRouter(LlamaCppBackend(), exact=False, config=cfg, pool=TierPool([top], min_confidence=0.95, max_tokens=1024))
    return ladder, ref


class Judge:
    def __init__(self) -> None:
        from chimera_core.ladder import TopBackend
        self.b = TopBackend(JUDGE_MODEL, {}, api_key=os.environ["GMI_API_KEY"], base_url=GMI, timeout=120)

    def ask(self, q: str, n: int = 1500) -> tuple[str, dict]:
        t0 = time.perf_counter()
        txt = self.b.complete(q, n)
        u = self.b.last_usage or {}
        return txt, {"in": u.get("prompt_tokens", 0), "out": u.get("completion_tokens", 0), "ms": round((time.perf_counter() - t0) * 1000)}


def _log(row) -> None:
    EVAL_LOG.parent.mkdir(parents=True, exist_ok=True)
    with EVAL_LOG.open("a") as fh:
        fh.write(row.model_dump_json() + "\n")


def _evalrow(run: str, mode: str, item: str, **kw):
    import sys
    sys.path.insert(0, str(ROOT / "bench"))
    import evallog
    return evallog.EvalRow(run_id=run, dataset=f"replay-{run}", item_id=item, mode=mode, ts=time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()), **kw)


def _top_usage(tel) -> tuple[int, int]:
    u = (tel.per_tier or {}).get("crusoe")
    return (u.input_tokens, u.output_tokens) if u else (0, 0)


def run_one(ladder, r: Req, out_default: int = 300) -> dict:
    """One request through the ladder. A tier error that escapes is recorded, not raised."""
    t0 = time.perf_counter()
    try:
        res = ladder.generate(r.prompt, task="replay")
        if ladder.shared is not None:
            ladder.shared.flush()  # the next request must see this answer
    except Exception as e:  # noqa: BLE001  AllTiersFailed or a tier error
        return {"type": "req", "id": r.id, "error": f"{type(e).__name__}: {e}"[:200], "ms": round((time.perf_counter() - t0) * 1000)}
    t = res.telemetry
    cache = t.tier_used in ("exact_cache", "semantic_cache")
    ttin, ttout = _top_usage(t)
    ans_tokens = est_tokens(res.text)
    return {"type": "req", "id": r.id, "tier": t.tier_name or t.tier_used, "cache": t.tier_used if cache else None,
            "cls": ("repeat" if t.tier_used == "exact_cache" else "near_repeat") if cache else kind(r.prompt),
            "tin": r.tokens_in if r.tokens_in is not None else est_tokens(r.prompt) + r.sys_chars // 4,
            "tout": r.tokens_out if r.tokens_out is not None else ans_tokens,
            "tokens_logged": r.tokens_in is not None and r.tokens_out is not None,
            "ladder_top_tokens": ttin + ttout, "ladder_usd": t.dollars_spent or 0.0, "ms": round(t.latency_ms),
            "model_tokens": [t.tokens_in, t.tokens_out], "answer": res.text, "error": "",
            "path": [{k: e.get(k) for k in ("step", "tier", "ok", "ms", "confidence", "error")} for e in (t.events or [])
                     if e.get("step") in ("call", "draft")]}  # why a request climbed: 30B confidence or an error


def run(reqs: list[Req], name: str, judge_n: int = 30, seed: int = 0) -> list[dict]:
    """All records: req rows, ref rows (763B answer + judge score for a sample of 30B answers), cachejudge rows."""
    from chimera_core.config import load_env
    load_env()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    out = SCRATCH / f"replay_live_{name}.jsonl"
    recs = [json.loads(x) for x in out.read_text().splitlines()] if out.exists() else []
    have = {(x["type"], x["id"]) for x in recs}
    tenant = f"replay-{name}"
    ladder, ref = build(tenant)
    print("purged", ladder.shared.purge(), "old rows in tenant", tenant, flush=True)
    for t in ladder.pool.tiers:  # load the models; not timed, not cached
        if t.device != "cloud":
            try:
                ladder.pool._factory(t).complete("hello", 4)
            except Exception as e:  # noqa: BLE001
                print("warm-up failed", t.name, type(e).__name__, flush=True)
    judge = Judge()
    by_id = {r.id: r for r in reqs}

    def put(rec: dict) -> None:
        recs.append(rec)
        have.add((rec["type"], rec["id"]))
        with out.open("a") as fh:
            fh.write(json.dumps(rec) + "\n")

    try:
        for i, r in enumerate(reqs):
            if ("req", r.id) in have:
                continue
            rec = run_one(ladder, r)
            put(rec)
            print("req", i + 1, len(reqs), rec.get("tier", "ERR"), rec["ms"], rec.get("error", ""), flush=True)
            _log(_evalrow(name, "replay-ladder", r.id, tier=_cls(rec.get("tier")), model=rec.get("tier"),
                          tokens_in=(rec.get("model_tokens") or [None])[0], tokens_out=(rec.get("model_tokens") or [0, None])[1],
                          dollars=rec.get("ladder_usd"), latency_ms=rec["ms"], notes=rec.get("error") or f"cls={rec.get('cls')}"))
        pool = [x for x in recs if x["type"] == "req" and x.get("tier") == "gpu-small" and not x.get("error")]
        for x in random.Random(seed).sample(pool, min(judge_n, len(pool))):
            if ("ref", x["id"]) in have:
                continue
            q = by_id[x["id"]].prompt
            t0 = time.perf_counter()
            try:
                rr = ref.generate(q, task="replay-reference")
                tt = rr.telemetry
                txt, jc = judge.ask(_score_prompt(q, rr.text, x["answer"]))
                score = _parse_score(txt)
            except Exception as e:  # noqa: BLE001
                print("ref/judge failed", x["id"], type(e).__name__, flush=True)
                continue
            put({"type": "ref", "id": x["id"], "score": score, "ref_tokens": [tt.tokens_in, tt.tokens_out], "ref_usd": tt.dollars_spent or 0.0,
                 "judge": jc, "ms": round((time.perf_counter() - t0) * 1000)})
            _log(_evalrow(name, "replay-reference", x["id"], tier="cloud", model=TOP_MODEL, tokens_in=tt.tokens_in, tokens_out=tt.tokens_out,
                          dollars=tt.dollars_spent, latency_ms=tt.latency_ms))
            _log(_evalrow(name, "replay-judge", x["id"], tier="cloud", model=JUDGE_MODEL, tokens_in=jc["in"], tokens_out=jc["out"],
                          dollars=prices.usd(jc["in"], jc["out"], prices.JUDGE), latency_ms=jc["ms"],
                          passed=None if score is None else score >= PASS_SCORE, grader=f"{JUDGE_MODEL} 1-5 vs 763B answer, pass >= {PASS_SCORE}"))
            print("judge", x["id"], score, flush=True)
        for x in [x for x in recs if x["type"] == "req" and x.get("cache") == "semantic_cache"]:
            if ("cachejudge", x["id"]) in have:
                continue
            try:
                txt, jc = judge.ask(YESNO.format(q=by_id[x["id"]].prompt, a=x["answer"]), 1500)
            except Exception as e:  # noqa: BLE001
                print("cache judge failed", x["id"], type(e).__name__, flush=True)
                continue
            ok = "YES" in txt.upper()
            put({"type": "cachejudge", "id": x["id"], "ok": ok, "judge": jc})
            _log(_evalrow(name, "replay-judge", x["id"] + ":cache", tier="cloud", model=JUDGE_MODEL, tokens_in=jc["in"], tokens_out=jc["out"],
                          dollars=prices.usd(jc["in"], jc["out"], prices.JUDGE), latency_ms=jc["ms"], passed=ok, grader="yes/no: cached answer fits the new prompt"))
    finally:
        print("purged", ladder.shared.purge(), "rows from tenant", tenant, flush=True)
    return recs


def _cls(tier: str | None) -> str | None:
    return {"gpu-small": "gpu", "cloud-deepseek": "cloud"}.get(tier or "", tier)


def _score_prompt(q: str, reference: str, answer: str) -> str:
    return (f"Question:\n{q}\n\nReference answer (one acceptable answer, not the only one):\n{reference}\n\n"
            f"Score the answer below 1-5 for correctness and helpfulness (5 best). Reply with ONLY JSON like {{\"score\": 4}}.\n\n"
            f"### Answer\n{answer}")


def _parse_score(txt: str) -> int | None:
    m = re.search(r"\"?score\"?\s*[:=]\s*([1-5])", txt) or re.search(r"\b([1-5])\b", txt)
    return int(m.group(1)) if m else None


def rows_and_rates(recs: list[dict]) -> tuple[list[dict], dict, dict]:
    """(summary rows, measured rates, quality stats) from live records. Failed requests are dropped from the cost rows and counted."""
    reqs = [x for x in recs if x["type"] == "req" and not x.get("error")]
    failed = sum(1 for x in recs if x["type"] == "req" and x.get("error"))
    scores = {x["id"]: x["score"] for x in recs if x["type"] == "ref" and x["score"] is not None}
    cj = {x["id"]: x["ok"] for x in recs if x["type"] == "cachejudge"}
    rows = []
    for x in reqs:
        rows.append({"id": x["id"], "cls": x["cls"], "tin": x["tin"], "tout": x["tout"], "est_tokens": not x["tokens_logged"],
                     "ladder_top_tokens": x["ladder_top_tokens"], "ladder_usd": x["ladder_usd"], "tier": x["tier"],
                     "wrong_hit": 1.0 if cj.get(x["id"]) is False else 0.0,
                     "bad_answer": 1.0 if scores.get(x["id"], PASS_SCORE) < PASS_SCORE else 0.0})
    p30: dict[str, float] = {}
    for c in ("easy_code", "lookup", "general", "hard"):
        sub = [x for x in reqs if x["cls"] == c]
        if sub:
            p30[c] = sum(x["tier"] == "gpu-small" for x in sub) / len(sub)
    hits = [x for x in reqs if x.get("cache") == "semantic_cache"]
    mean_out = sum(x["tout"] for x in reqs) / len(reqs) if reqs else 300
    rates = {"source": f"measured on a live run of {len(reqs)} requests", "p30": p30,
             "agree": (sum(s >= PASS_SCORE for s in scores.values()) / len(scores)) if scores else None,
             "wrong_hit": (sum(cj[h["id"]] is False for h in hits if h["id"] in cj) / len(hits)) if hits else 0.0,
             "out_tokens": round(mean_out)}
    quality = {"judged": len(scores), "passed": sum(s >= PASS_SCORE for s in scores.values()), "failed_requests": failed,
               "semantic_hits": len(hits), "semantic_hits_judged": len(cj), "wrong_cache_hits": sum(v is False for v in cj.values()),
               "exact_hits": sum(x.get("cache") == "exact_cache" for x in reqs),
               "judge_usd": sum(prices.usd(x["judge"]["in"], x["judge"]["out"], prices.JUDGE) for x in recs if x["type"] in ("ref", "cachejudge")),
               "ref_usd": sum(x["ref_usd"] for x in recs if x["type"] == "ref")}
    return rows, rates, quality
