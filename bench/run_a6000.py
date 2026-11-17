"""Owned-hardware proof on the shared A6000 box: plain 30B (PLAIN) vs our ladder (POOL). bench/results_a6000.md

    PLAIN: every item to the self-hosted model alone (one-tier pool, no cache, no 763B).
    POOL : Supabase cache (exact hash on the normalized prompt, then cosine >= 0.97 + guard; own tenant per repeat,
           purged before and after) -> the self-hosted model (confidence gate 0.95) -> Crusoe 763B.
           Code items run their tests on the self-hosted answer; a failing answer climbs one tier to the 763B.
           Only answers that pass their tests (or the gate, for plain Q&A) are cached.

The model is served by bench/a6000/serve.sh on whichever GPU bench/a6000/watchdog.sh finds free, behind a token
proxy and a Cloudflare quick tunnel. Every call goes through SpeculativeCascadeRouter.generate().

    .venv/bin/python bench/run_a6000.py speed qwen                       # cold load, tokens/s (1 and 16 streams)
    .venv/bin/python bench/run_a6000.py run qwen:PLAIN:suite:1 qwen:POOL:cost:1 ...   # streams run in parallel
    .venv/bin/python bench/run_a6000.py report

Needs in .env: A6000_SSH (ssh alias of the box), A6000_ROOT (run folder on the box), CHIMERA_GPU_KEY, CRUSOE_API_KEY,
CHIMERA_DB_URL. The tunnel URL is read from the box over ssh and written only to .env (CHIMERA_GPU_URL) and the
git-ignored scratch folder. Rows: bench/.scratch/a6000/<model>_<mode>_<data>_r<rep>.jsonl, one per item; a rerun
skips finished ids. A row is dropped and redone if the GPU went away during it (a yield), so yields never turn
into 763B calls.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import pathlib
import re
import subprocess
import sys
import threading
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench"))
sys.path.insert(0, str(ROOT / "bench" / "datasets"))
import run_suite  # noqa: E402  (sets up sys.path and conftest)
import grade  # noqa: E402
from chimera_core import RouterConfig, SpeculativeCascadeRouter  # noqa: E402
from chimera_core.cache.guard import make_guard  # noqa: E402
from chimera_core.cache.pgvector_cache import PgStore, PgVectorCache  # noqa: E402
from chimera_core.cache.semantic_cache import CachedEmbedder, OnnxMiniLMEmbedder  # noqa: E402
from chimera_core.config import product_tier  # noqa: E402
from chimera_core.inference.local_draft import LlamaCppBackend  # noqa: E402
from chimera_core.router import complexity_score  # noqa: E402
from chimera_core.tiers import TierPool  # noqa: E402
from run_bench import load_env  # noqa: E402

STORE = ROOT / "bench/.scratch/a6000"
MODELS = {"qwen": ("qwen3:30b-instruct", "qwen"), "gemma": ("gemma2:9b", "gemma")}
DATA = {"suite": ROOT / "bench/datasets/suite.jsonl", "cost": ROOT / "bench/cost_case/tasks.jsonl"}
TOP = run_suite.TOP_TIER
GPU = "gpu-small"
_env_lock, _emb_lock = threading.Lock(), threading.Lock()


# ---------------------------------------------------------------- the box ----
def ssh(cmd: str, timeout: int = 30) -> str:
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", os.environ["A6000_SSH"], cmd],
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout).stdout


def endpoints() -> list[str]:
    """Live tunnel URLs, one per GPU we hold now. Written to .env (CHIMERA_GPU_URL = the first) and scratch only."""
    r = os.environ["A6000_ROOT"]
    try:
        out = ssh(f"cd {r}/run && for f in gpu*.url; do [ -s $f ] && cat $f; done 2>/dev/null")
    except subprocess.TimeoutExpired:
        return []
    urls = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", out)
    if urls:
        with _env_lock:
            os.environ["CHIMERA_GPU_URL"] = urls[0]
            p = ROOT / ".env"
            t = p.read_text()
            line = f"CHIMERA_GPU_URL={urls[0]}"
            t2 = re.sub(r"^CHIMERA_GPU_URL=.*$", line, t, flags=re.M) if re.search(r"^CHIMERA_GPU_URL=", t, re.M) else t + line + "\n"
            if t2 != t:
                p.write_text(t2)
                p.chmod(0o600)
            STORE.mkdir(parents=True, exist_ok=True)
            (STORE / "endpoints.json").write_text(json.dumps({"at": time.time(), "urls": urls}))
    return urls


_eps: dict = {"at": 0.0, "urls": []}


def cached_endpoints(force: bool = False) -> list[str]:
    """endpoints(), re-read from the box at most every 60 s unless forced (a URL stopped answering)."""
    if force or time.time() - _eps["at"] > 60 or not _eps["urls"]:
        _eps["urls"], _eps["at"] = endpoints(), time.time()
    return list(_eps["urls"])


def loaded(url: str, model: str) -> bool:
    req = urllib.request.Request(url + "/api/ps", headers={"Authorization": "Bearer " + os.environ["CHIMERA_GPU_KEY"]})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310
            return any(m.get("name", "").startswith(model) for m in json.load(r).get("models", []))
    except Exception:  # noqa: BLE001
        return False


def up(url: str) -> bool:
    req = urllib.request.Request(url + "/api/version", headers={"Authorization": "Bearer " + os.environ["CHIMERA_GPU_KEY"]})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def raw_generate(url: str, model: str, prompt: str, n: int) -> dict:
    """Direct Ollama call, used only by `speed` (a hardware number, like results_akash_tuning.md)."""
    body = json.dumps({"model": model, "prompt": prompt, "stream": False, "think": False, "keep_alive": -1,
                       "options": {"num_predict": n, "temperature": 0}}).encode()
    req = urllib.request.Request(url + "/api/generate", data=body, headers={
        "Authorization": "Bearer " + os.environ["CHIMERA_GPU_KEY"], "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:  # noqa: S310
        return json.load(r)


# ---------------------------------------------------------------- runs ----
class LockedEmbedder:
    """One MiniLM for every stream in this process (memory on the Mac is tight)."""

    def __init__(self) -> None:
        self.inner = CachedEmbedder(OnnxMiniLMEmbedder())

    def embed(self, text: str):
        with _emb_lock:
            return self.inner.embed(text)


def gpu_tier(model: str, url: str, plain: bool):
    name, family = MODELS[model]
    return product_tier(GPU).model_copy(update={
        "url": url, "model": name, "family": family, "api_key_env": "CHIMERA_GPU_KEY",
        "max_complexity": 1.0 if plain else product_tier(GPU).max_complexity})


def items(data: str, model: str) -> list[dict]:
    rows = [json.loads(x) for x in DATA[data].read_text().splitlines()]
    if model == "gemma":  # shortcut: the second model runs a fixed slice (time box); pairs are kept whole
        if data == "suite":
            per: dict[str, int] = {}
            keep = set()
            for r in rows:
                if r["source"] == "qqp":
                    continue
                if per.get(r["source"], 0) < 12:
                    per[r["source"]] = per.get(r["source"], 0) + 1
                    keep.add(r["id"])
            pairs = [r for r in rows if r["source"] == "qqp" and r["data"].get("role") == "b"][:12]
            keep |= {r["id"] for r in pairs} | {r["data"]["a_id"] for r in pairs}
            rows = [r for r in rows if r["id"] in keep]
        else:
            keep = set()
            for d in ("trivial", "everyday", "hard"):
                g = sorted(r["id"] for r in rows if r["difficulty"] == d)
                keep |= {g[int(i * len(g) / 25)] for i in range(25)}
            rows = [r for r in rows if r["id"] in keep]
    return rows


class Stream:
    def __init__(self, spec: str, emb: LockedEmbedder) -> None:
        self.model, self.mode, self.data, rep = spec.split(":")
        self.rep = int(rep)
        self.spec = spec
        self.out = STORE / f"{self.model}_{self.mode}_{self.data}_r{self.rep}.jsonl"
        self.tenant = f"a6000-{self.model}-{self.data}-r{self.rep}"
        self.shared = None
        self.pool_out = STORE / f"{self.model}_POOL_{self.data}_r{self.rep}.jsonl"
        if self.mode in ("POOL", "WARM"):  # WARM: the same items again, on the cache POOL left behind
            dsn = os.environ["CHIMERA_DB_URL"]
            # one connection per stream: Supabase's session pooler allows 15 clients, and 18 streams x 4 filled it
            self.shared = PgVectorCache(emb, lambda: PgStore(dsn, max_size=1), threshold=0.97, tenant=self.tenant, store_text=True,
                                        guard=make_guard(), budget_s=3.0, cooldown_s=0.0, max_strikes=10**9)
        self.emb = emb if self.shared is not None else None
        self.routers: dict[str, tuple] = {}
        self.top = self._router(TierPool([TOP], min_confidence=0.95, max_tokens=1024))

    def _router(self, pool: TierPool) -> tuple:
        last: dict = {}
        orig = pool.generate

        def spy(*a, **kw):
            last["r"] = r = orig(*a, **kw)
            return r
        pool.generate = spy
        return SpeculativeCascadeRouter(LlamaCppBackend(), exact=False, shared=self.shared, embedder=self.emb,
                                        config=RouterConfig(min_confidence=0.95), pool=pool), last

    def router(self, url: str) -> tuple:
        if url not in self.routers:
            g = gpu_tier(self.model, url, self.mode == "PLAIN")
            tiers = [g] if self.mode == "PLAIN" else [g, TOP]
            self.routers[url] = self._router(TierPool(tiers, min_confidence=0.95, max_tokens=1024))
        return self.routers[url]

    def wait_gpu(self) -> str:
        """Block until a GPU of ours serves the model (after a yield the watchdog restarts it; we warm it, untimed)."""
        name = MODELS[self.model][0]
        fresh = False
        while True:
            urls = cached_endpoints(force=fresh)
            fresh = True
            for u in urls[self.rep % max(len(urls), 1):] + urls:
                if loaded(u, name):
                    return u
                if up(u):
                    try:
                        raw_generate(u, name, "hello", 2)  # cold load after a (re)start; not timed
                    except Exception:  # noqa: BLE001
                        pass
                    if loaded(u, name):
                        return u
            print(self.spec, "waiting for a free GPU", flush=True)
            time.sleep(15)

    def one(self, row: dict, url: str) -> dict | None:
        router, last = self.router(url)
        last.clear()
        is_code = row["grader"] == "unit_test"
        check = (lambda a, row=row: bool(grade.grade(row, a))) if is_code and self.mode != "PLAIN" else None
        t0 = time.perf_counter()
        err, escalated = "", False
        try:
            res = router.generate(row["prompt"], check=check)
            if router.shared is not None:
                router.shared.flush()
            text, tier = res.text, res.telemetry.tier_used
            r = last.get("r")
            per = {k: v.model_dump() for k, v in r.per_tier.items()} if r else {}
            attempts = list(r.attempts) if r else []
            if r:
                tier = r.tier
            # the answer check for code: a 30B answer that fails its tests climbs one tier (the 763B)
            if check is not None and r is not None and tier == GPU and not check(text):
                trouter, tlast = self.top
                tlast.clear()
                res2 = trouter.generate(row["prompt"], check=check)
                trouter.shared.flush()
                r2 = tlast.get("r")
                if r2 is not None:
                    text, tier, escalated = res2.text, r2.tier, True
                    attempts += list(r2.attempts)
                    for k, v in r2.per_tier.items():
                        per[k] = v.model_dump()
        except Exception as e:  # noqa: BLE001  AllTiersFailed or a tier error that escaped
            text, tier, per, attempts, err = "", "failed", {}, [], f"{type(e).__name__}: {e}"[:200]
        ms = (time.perf_counter() - t0) * 1000
        # a yield during this item: the GPU tier errored or was skipped while it should have answered -> redo later
        gpu_should = self.mode == "PLAIN" or complexity_score(row["prompt"]) <= gpu_tier(self.model, url, False).max_complexity
        cached = tier in ("exact_cache", "semantic_cache")
        gpu_err = per.get(GPU, {}).get("errors", 0) > 0 or (gpu_should and not cached and GPU not in attempts)
        if (gpu_err or tier == "failed") and not (up(url) and loaded(url, MODELS[self.model][0])):
            pool = router.pool
            for d in (pool._health, pool._fails, pool._open_until, pool._backends):
                d.clear()
            return None
        return {"id": row["id"], "spec": self.spec, "model": MODELS[self.model][0], "mode": self.mode, "data": self.data,
                "rep": self.rep, "tier": tier, "escalated_by_tests": escalated, "latency_ms": round(ms), "answer": text,
                "attempts": attempts, "per_tier": per, "error": err, "at": time.time(),
                "grade": grade.grade(row, text) if text else (0 if row["grader"] not in ("pair", "llm") else None)}

    def run(self) -> str:
        rows = items(self.data, self.model)
        ids = {r["id"] for r in rows}
        if self.mode == "WARM":  # starts once its POOL repeat has every row, on the cache that repeat filled
            while not (self.pool_out.exists() and ids <= {json.loads(x)["id"] for x in self.pool_out.read_text().splitlines()}):
                time.sleep(30)
        done = {json.loads(x)["id"] for x in self.out.read_text().splitlines()} if self.out.exists() else set()
        if self.mode == "POOL" and not done:
            print(self.spec, "purged", self.shared.purge(), "old rows in", self.tenant, flush=True)
        t0 = time.time()
        with self.out.open("a") as fh:
            for row in rows:
                if row["id"] in done:
                    continue
                while True:
                    rec = self.one(row, self.wait_gpu())
                    if rec is not None:
                        break
                    print(self.spec, row["id"], "dropped (GPU went away), redo", flush=True)
                fh.write(json.dumps(rec) + "\n")
                fh.flush()
                print(self.spec, row["id"], rec["tier"], rec["latency_ms"], rec["grade"], rec["error"], flush=True)
        left = ids - {json.loads(x)["id"] for x in self.out.read_text().splitlines()}
        if self.mode == "WARM" and not left:  # POOL keeps its rows for WARM; WARM cleans the tenant up
            print(self.spec, "purged", self.shared.purge(), "rows after the run", flush=True)
        return f"{self.spec} finished in {time.time() - t0:.0f} s"


def run(specs: list[str]) -> None:
    load_env()
    STORE.mkdir(parents=True, exist_ok=True)
    emb = LockedEmbedder() if any(":POOL:" in s or ":WARM:" in s for s in specs) else None
    if emb:
        emb.embed("warm up")
    streams = [Stream(s, emb) for s in specs]
    with cf.ThreadPoolExecutor(len(streams)) as ex:
        for f in cf.as_completed([ex.submit(s.run) for s in streams]):
            print(f.result(), flush=True)


def speed(model: str) -> None:
    """Cold load and decode speed on the GPU we hold. Rows: bench/.scratch/a6000/speed_<model>.json."""
    load_env()
    name = MODELS[model][0]
    url = [u for u in endpoints() if up(u)][-1]  # the last GPU we hold (the runs pick theirs by repeat number)
    prompt = "Write a Python function that returns the n-th Fibonacci number, with a docstring and three tests."
    first = raw_generate(url, name, prompt, 256)  # cold if the model was not loaded yet
    one = [raw_generate(url, name, prompt, 256) for _ in range(3)]
    t0 = time.perf_counter()
    with cf.ThreadPoolExecutor(16) as ex:
        many = list(ex.map(lambda _: raw_generate(url, name, prompt, 256), range(16)))
    wall = time.perf_counter() - t0
    tps = [x["eval_count"] / (x["eval_duration"] / 1e9) for x in one]
    out = {"model": name, "load_s": first.get("load_duration", 0) / 1e9, "first_total_s": first.get("total_duration", 0) / 1e9,
           "decode_tok_s_1_stream": sum(tps) / len(tps),
           "aggregate_tok_s_16_streams": sum(x["eval_count"] for x in many) / wall,
           "per_stream_tok_s_16": sum(x["eval_count"] / (x["eval_duration"] / 1e9) for x in many) / 16,
           "prompt_tok_s": one[0]["prompt_eval_count"] / max(one[0]["prompt_eval_duration"] / 1e9, 1e-9)}
    vram = ssh("nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader")
    out["vram"] = vram.strip()
    (STORE / f"speed_{model}.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "run":
        run(sys.argv[2:])
    elif cmd == "purge":  # clean every a6000 tenant (rows this bench wrote; nothing else is touched)
        load_env()
        emb = LockedEmbedder()
        for m in MODELS:
            for d in DATA:
                for rep in (1, 2, 3, 4, 5):
                    print(m, d, rep, Stream(f"{m}:WARM:{d}:{rep}", emb).shared.purge())
    elif cmd == "speed":
        speed(sys.argv[2])
    elif cmd in ("up", "down"):  # live demo: serve the 30B on a free GPU (still yields to anyone), or stop and restore
        load_env()
        ssh(f"echo {'run' if cmd == 'up' else 'stop'} > {os.environ['A6000_ROOT']}/run/want")
        if cmd == "up":
            for _ in range(40):  # the watchdog starts it after 60 s clear; the tunnel URL shows a few seconds later
                if endpoints():
                    print("A6000 30B up: CHIMERA_GPU_URL in .env points at it (restart the web server to pick it up)")
                    break
                time.sleep(10)
            else:
                print("no GPU free yet; the watchdog keeps trying")
        else:
            p = ROOT / ".env"
            t = p.read_text()
            m = re.search(r"^CHIMERA_GPU_URL_AKASH=(.*)$", t, re.M)
            if m:
                p.write_text(re.sub(r"^CHIMERA_GPU_URL=.*$", lambda _: "CHIMERA_GPU_URL=" + m.group(1), t, flags=re.M))
                p.chmod(0o600)
            print("A6000 servers and tunnels stopped; CHIMERA_GPU_URL restored")
    elif cmd == "report":
        import a6000_report
        a6000_report.main()
