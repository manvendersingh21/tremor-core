"""One log for every benchmark run: EvalRow schema, CSV/JSONL importers, SQLite + Supabase store, leaderboard.

Run: bin/chimera evals import|list|leaderboard.  Importers only read the result files and never invent a value:
a field the source file lacks stays None. `ts` is the source file's modification time (the files hold no run time).
"""
from __future__ import annotations

import csv
import json
import os
import pathlib
import sqlite3
import statistics
from datetime import datetime, timezone

from pydantic import BaseModel

BENCH = pathlib.Path(__file__).resolve().parent
ROOT = BENCH.parent
DB_PATH = pathlib.Path(os.environ.get("CHIMERA_EVALS_DB", "~/.chimera/evals.db")).expanduser()
TENANT = "bench"
SUITE_LOGS = [BENCH / ".scratch" / "eval_log.jsonl"]  # written by bench/run_suite.py
BASELINES = ("A", "G", "T", "TOP", "big model alone", "ollama")  # first one present in a dataset is its baseline
COLS = ["run_id", "ts", "source_file", "dataset", "item_id", "mode", "tier", "model", "tokens_in", "tokens_out",
        "cached_tokens", "dollars", "latency_ms", "passed", "grader", "notes"]


class EvalRow(BaseModel):
    run_id: str
    ts: str | None = None
    source_file: str | None = None
    dataset: str
    item_id: str
    mode: str
    tier: str | None = None  # exact_cache | semantic_cache | mac | gpu | cloud, else the raw name
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cached_tokens: int | None = None
    dollars: float | None = None
    latency_ms: float | None = None
    passed: bool | None = None
    grader: str | None = None
    notes: str | None = None


def tier_class(raw: str | None) -> str | None:
    t = (raw or "").lower()
    if not t:
        return None
    if "cache" in t:
        return t
    for cls, keys in (("mac", ("mac", "local")), ("gpu", ("gpu", "mid")), ("cloud", ("cloud", "top", "crusoe"))):
        if t.startswith(keys):
            return cls
    return raw


def _n(v) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _i(v) -> int | None:
    x = _n(v)
    return None if x is None else int(x)


def _ts(p: pathlib.Path) -> str:
    return datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")


def _read(p: pathlib.Path) -> list[dict]:
    with open(p, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _common(p: pathlib.Path) -> dict:
    return {"run_id": p.stem, "ts": _ts(p), "source_file": p.name}


def _binary(r: dict, grade: str | None = None) -> tuple[bool | None, str | None, str | None]:
    """quality is 0/1 for easy/code_small/paraphrase/repeat (keyword or assert check). Heavy code has a 1-5 model grade."""
    if r.get("cat") == "code_heavy":
        g = grade if grade not in (None, "") else r.get("quality")
        return None, "llm 1-5 (Qwen/Qwen3.8-27B)" if g not in (None, "") else None, f"heavy_grade={g}" if g not in (None, "") else None
    q = r.get("quality")
    return (None if q in (None, "") else q == "1"), ("assert/keyword check" if q not in (None, "") else None), None


def import_results(p: pathlib.Path) -> list[EvalRow]:
    """results.csv: A cloud only, B cascade. Tokens are Crusoe's; local_tokens are the Mac's (no in/out split)."""
    out = []
    for r in _read(p):
        passed, grader, note = _binary(r)
        notes = [f"cat={r['cat']}", f"tier_raw={r['tier']}"] + ([note] if note else [])
        if _i(r["local_tokens"]):
            notes.append(f"mac_tokens={_i(r['local_tokens'])}")
        out.append(EvalRow(**_common(p), dataset="bench30-crusoe", item_id=r["id"], mode=r["mode"], tier=tier_class(r["tier"]),
                           tokens_in=_i(r["cloud_prompt_tokens"]), tokens_out=_i(r["cloud_completion_tokens"]),
                           cached_tokens=_i(r["cloud_cached_tokens"]), dollars=_n(r["usd"]), latency_ms=_n(r["latency_ms"]),
                           passed=passed, grader=grader, notes="; ".join(notes)))
    return out


def import_gpu(p: pathlib.Path) -> list[EvalRow]:
    """results_gpu.csv: G GPU only, H cascade. Its 'cloud_handoff' rows ran on the GPU, so tier is gpu. No dollars column."""
    out = []
    for r in _read(p):
        passed, grader, note = _binary(r)
        notes = [f"cat={r['cat']}", f"tier_raw={r['tier']}"] + ([note] if note else [])
        if _i(r["local_tokens"]):
            notes.append(f"mac_tokens={_i(r['local_tokens'])}")
        t = "gpu" if r["tier"] == "cloud_handoff" else tier_class(r["tier"])
        out.append(EvalRow(**_common(p), dataset="bench30-gpu", item_id=r["id"], mode=r["mode"], tier=t,
                           tokens_in=_i(r["gpu_prompt_tokens"]), tokens_out=_i(r["gpu_completion_tokens"]),
                           latency_ms=_n(r["latency_ms"]), passed=passed, grader=grader, notes="; ".join(notes)))
    return out


def import_ladder(p: pathlib.Path) -> list[EvalRow]:
    """results_ladder.csv: top tokens if the top tier ran, else GPU tokens. The other side goes in notes."""
    out = []
    for r in _read(p):
        passed, grader, note = _binary(r, r.get("heavy_grade"))
        top_in, top_out = _i(r["top_prompt_tokens"]), _i(r["top_completion_tokens"])
        gin, gout = _i(r["gpu_prompt_tokens"]), _i(r["gpu_completion_tokens"])
        use_top = bool((top_in or 0) + (top_out or 0))
        notes = [f"cat={r['cat']}", f"tier_raw={r['tier']}"] + ([note] if note else [])
        if use_top and (gin or gout):
            notes.append(f"gpu_tokens={gin}/{gout}")
        out.append(EvalRow(**_common(p), dataset="bench30-ladder", item_id=r["id"], mode=r["mode"], tier=tier_class(r["tier"]),
                           tokens_in=top_in if use_top else gin, tokens_out=top_out if use_top else gout,
                           cached_tokens=_i(r["top_cached_tokens"]), dollars=_n(r["top_usd"]), latency_ms=_n(r["latency_ms"]),
                           passed=passed, grader=grader, notes="; ".join(notes)))
    return out


def import_spec(p: pathlib.Path) -> list[EvalRow]:
    """spec_results.csv: one row per prompt and K. 'ollama' is the plain GPU baseline. No quality column."""
    out = []
    for r in _read(p):
        base = r["K"] == "ollama"
        total = _n(r["total_s"])
        notes = [f"cat={r['cat']}"] + ([] if base else [f"alpha={r['alpha']}", f"rounds={r['rounds']}", f"tok_s={r['tok_s']}"])
        out.append(EvalRow(**_common(p), dataset="bench30-spec", item_id=r["id"], mode="ollama" if base else f"spec-K{r['K']}",
                           tokens_out=_i(r["new_tokens"]), latency_ms=None if total is None else total * 1000,
                           notes="; ".join(notes)))
    return out


def import_specplus(p: pathlib.Path) -> list[EvalRow]:
    """results_specplus.csv: aggregate simulation rows, not per-prompt. item_id is the section plus network setting; tokens is generated tokens."""
    out = []
    for r in _read(p):
        notes = [f"{k}={r[k]}" for k in ("alpha", "bytes_per_rt", "passes_per_100", "tok_s", "lossy_wrong_per_100") if r.get(k) not in (None, "", "-")]
        out.append(EvalRow(**_common(p), dataset=f"specplus-{r['section']}", item_id=f"{r['section']}-rtt{r['rtt_ms']}-srv{r['srv_ms']}",
                           mode=r["setup"], tokens_out=_i(r["tokens"]), notes="; ".join(notes)))
    return out


def import_suite(p: pathlib.Path) -> list[EvalRow]:
    """suite_TOP/POOL.jsonl from bench/run_suite.py. Tokens are the answering tier's; dollars sum all tiers tried."""
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        per = d.get("per_tier") or {}
        mine = per.get(d["tier"]) or {}
        others = {k: f"{v.get('tokens_in')}/{v.get('tokens_out')}" for k, v in per.items() if k != d["tier"]}
        notes = [f"attempts={'>'.join(d.get('attempts') or [])}"] + ([f"other_tier_tokens={others}"] if others else []) + ([f"error={d['error']}"] if d.get("error") else [])
        g = d.get("grade")
        out.append(EvalRow(**_common(p), dataset=d["id"].split("-")[0], item_id=d["id"], mode=d["mode"], tier=tier_class(d["tier"]),
                           model=d["tier"], tokens_in=mine.get("tokens_in"), tokens_out=mine.get("tokens_out"),
                           dollars=sum(v.get("dollars") or 0 for v in per.values()) if per else None,
                           latency_ms=d.get("latency_ms"), passed=None if g is None else bool(g),
                           grader="bench/datasets/grade.py" if g is not None else None, notes="; ".join(notes)))
    return out


def import_jsonl(p: pathlib.Path) -> list[EvalRow]:
    """Rows already in EvalRow shape (the suite worker's eval_log.jsonl)."""
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(EvalRow(**{k: v for k, v in json.loads(line).items() if k in COLS}))
        except (json.JSONDecodeError, ValueError):
            pass
    return rows


def sources() -> list[tuple[pathlib.Path, callable]]:
    s = [(BENCH / "results.csv", import_results), (BENCH / "results_gpu.csv", import_gpu),
         (BENCH / "results_ladder.csv", import_ladder), (BENCH / "spec_results.csv", import_spec),
         (BENCH / "results_specplus.csv", import_specplus)]
    logs = [p for p in SUITE_LOGS if p.is_file()]
    if logs:  # the suite writes EvalRows itself; the raw per-mode files hold the same items
        s += [(p, import_jsonl) for p in logs]
    else:
        s += [(p, import_suite) for p in sorted((BENCH / ".scratch").glob("suite_*.jsonl"))]
    return [(p, f) for p, f in s if p.is_file()]


def import_all() -> dict[str, list[EvalRow]]:
    """{source file name: rows}. A file that is mid-write or malformed is skipped with its error in the key's place."""
    out: dict[str, list[EvalRow]] = {}
    for p, fn in sources():
        try:
            out[p.name] = fn(p)
        except (OSError, KeyError, ValueError, csv.Error) as e:
            print(f"skip {p.name}: {e}")
    return out


# ---- store ---------------------------------------------------------------------------------------------------------
def connect(path: pathlib.Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute(f"create table if not exists eval_runs (tenant text not null default '{TENANT}', "
               "run_id text, ts text, source_file text, dataset text, item_id text, mode text, tier text, model text, "
               "tokens_in integer, tokens_out integer, cached_tokens integer, dollars real, latency_ms real, passed integer, "
               "grader text, notes text, primary key (run_id, item_id, mode))")
    return db


def upsert_sqlite(rows: list[EvalRow], path: pathlib.Path = DB_PATH) -> int:
    db = connect(path)
    sql = (f"insert into eval_runs ({','.join(COLS)}) values ({','.join('?' * len(COLS))}) "
           f"on conflict (run_id, item_id, mode) do update set {','.join(f'{c}=excluded.{c}' for c in COLS[1:])}")
    db.executemany(sql, [tuple(None if (v := getattr(r, c)) is None else (int(v) if c == "passed" else v) for c in COLS) for r in rows])
    db.commit()
    db.close()
    return len(rows)


def _env(name: str) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    f = ROOT / ".env"
    if f.is_file():
        for line in f.read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() == name and v.strip():
                return v.strip().strip("'\"")
    return None


def upsert_supabase(rows: list[EvalRow]) -> str:
    """Upsert into eval_runs (tenant='bench'). Needs CHIMERA_DB_URL and deploy/sql/004_eval_runs.sql applied. Returns a status line."""
    url = _env("CHIMERA_DB_URL")
    if not url:
        return "supabase: CHIMERA_DB_URL not set, skipped"
    try:
        import psycopg
    except ImportError:
        return "supabase: psycopg not installed, skipped"
    sql = (f"insert into eval_runs (tenant,{','.join(COLS)}) values ('{TENANT}',{','.join(['%s'] * len(COLS))}) "
           f"on conflict (run_id,item_id,mode) do update set {','.join(f'{c}=excluded.{c}' for c in COLS[1:])}")
    try:
        with psycopg.connect(url, connect_timeout=10) as con, con.cursor() as cur:
            cur.execute("select set_config('app.tenant', %s, true)", (TENANT,))
            for r in rows:  # one by one: executemany pipelines and its abort message prints the host
                cur.execute(sql, tuple(getattr(r, c) for c in COLS))
        return f"supabase: upserted {len(rows)} rows"
    except Exception as e:  # noqa: BLE001  report the class only; the message can carry the connection string
        return f"supabase: failed ({type(e).__name__}), local copy is complete"


def load_rows(path: pathlib.Path = DB_PATH) -> list[EvalRow]:
    """Rows from the SQLite file, or straight from the result files when it does not exist yet."""
    if not path.is_file():
        return [r for rs in import_all().values() for r in rs]
    db = connect(path)
    db.row_factory = sqlite3.Row
    rows = [EvalRow(**{**dict(x), "passed": None if x["passed"] is None else bool(x["passed"])})
            for x in db.execute(f"select {','.join(COLS)} from eval_runs order by dataset, mode, item_id")]
    db.close()
    return rows


# ---- leaderboard ---------------------------------------------------------------------------------------------------
def _pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    lo = int(k)
    return xs[lo] + (xs[min(lo + 1, len(xs) - 1)] - xs[lo]) * (k - lo)


def _tok(r: EvalRow) -> int:
    return (r.tokens_in or 0) + (r.tokens_out or 0)


def leaderboard(rows: list[EvalRow]) -> list[dict]:
    """One entry per (dataset, mode). Top-model tokens = tokens on the tier the baseline mode answers with.
    % saved compares only items both modes ran. `bad` lists columns where the mode is worse than its baseline."""
    ds: dict[str, dict[str, list[EvalRow]]] = {}
    for r in rows:
        ds.setdefault(r.dataset, {}).setdefault(r.mode, []).append(r)
    out = []
    for d, modes in ds.items():
        base = next((m for m in BASELINES if m in modes), next(iter(modes)))
        tiers = [r.tier for r in modes[base] if r.tier]
        big = statistics.mode(tiers) if tiers else None
        bt = {r.item_id: _tok(r) for r in modes[base] if r.tier == big}
        stats = {}
        for m, rs in modes.items():
            lat = [r.latency_ms for r in rs if r.latency_ms is not None]
            gr = [r.passed for r in rs if r.passed is not None]
            usd = [r.dollars for r in rs if r.dollars is not None]
            stats[m] = {"dataset": d, "mode": m, "baseline": m == base, "n": len(rs), "big_tier": big,
                        "top_tokens": sum(_tok(r) for r in rs if r.tier == big) if big else None,
                        "dollars": sum(usd) if usd else None, "p50_ms": _pct(lat, .5), "p90_ms": _pct(lat, .9),
                        "pass_rate": sum(gr) / len(gr) if gr else None, "graded": len(gr), "saved_pct": None}
        for m, rs in modes.items():
            ids = {r.item_id for r in rs}
            common = ids & {r.item_id for r in modes[base]}
            b = sum(bt.get(i, 0) for i in common)
            mine = sum(_tok(r) for r in rs if r.tier == big and r.item_id in common)
            stats[m]["saved_pct"] = None if m == base or not b or not big else 100 * (1 - mine / b)
        b0 = stats[base]
        for m, s in stats.items():
            s["bad"] = [] if s["baseline"] else [k for k, bad in (
                ("saved_pct", s["saved_pct"] is not None and s["saved_pct"] < 0),
                ("dollars", s["dollars"] is not None and b0["dollars"] is not None and s["dollars"] > b0["dollars"]),
                ("p50_ms", s["p50_ms"] is not None and b0["p50_ms"] is not None and s["p50_ms"] > b0["p50_ms"]),
                ("p90_ms", s["p90_ms"] is not None and b0["p90_ms"] is not None and s["p90_ms"] > b0["p90_ms"]),
                ("pass_rate", s["pass_rate"] is not None and b0["pass_rate"] is not None and s["pass_rate"] < b0["pass_rate"])) if bad]
            if any(s[k] is not None for k in ("top_tokens", "dollars", "p50_ms", "pass_rate")):  # aggregate rows (specplus) have none
                out.append(s)
    return out


def tokens_by_tier(rows: list[EvalRow]) -> list[dict]:
    """Tokens per (dataset, mode) split by the tier that answered: cache / mac / gpu / cloud. Cache hits carry 0 tokens."""
    acc: dict[tuple[str, str], dict[str, int]] = {}
    for r in rows:
        t = "cache" if (r.tier or "").endswith("cache") else (r.tier if r.tier in ("mac", "gpu", "cloud") else "other")
        a = acc.setdefault((r.dataset, r.mode), {"cache": 0, "mac": 0, "gpu": 0, "cloud": 0, "other": 0})
        a[t] += _tok(r)
    return [{"dataset": d, "mode": m, **a} for (d, m), a in acc.items()]


def api_payload(rows: list[EvalRow]) -> dict:
    keys = ["dataset", "item_id", "mode", "tier", "model", "tokens_in", "tokens_out", "cached_tokens", "dollars", "latency_ms", "passed", "run_id", "notes"]
    return {"leaderboard": leaderboard(rows), "tokens_by_tier": tokens_by_tier(rows), "n": len(rows),
            "rows": [r.model_dump(include=set(keys)) for r in rows]}


def main(args) -> int:
    """args from apps/kiro-trimmer/cli.py: .action import|list|leaderboard, .dataset, .mode, .limit"""
    if args.action == "import":
        per = import_all()
        rows = [r for rs in per.values() for r in rs]
        print(f"sqlite: upserted {upsert_sqlite(rows)} rows into {DB_PATH}")
        print(upsert_supabase(rows))
        for name, rs in per.items():
            print(f"  {name}: {len(rs)}")
        return 0
    rows = load_rows()
    if args.action == "list":
        sel = [r for r in rows if (not args.dataset or r.dataset == args.dataset) and (not args.mode or r.mode == args.mode)]
        for r in sel[: args.limit]:
            print(f"{r.dataset:16} {r.mode:10} {r.item_id:14} {r.tier or '-':14} tok={_tok(r):6} ${r.dollars if r.dollars is not None else '-'} "
                  f"{'' if r.latency_ms is None else int(r.latency_ms)}ms pass={r.passed}")
        print(f"{len(sel)} rows")
        return 0
    f = lambda v, s="": "-" if v is None else f"{v:.1f}{s}"  # noqa: E731
    print(f"{'dataset':16} {'mode':14} {'N':>4} {'top tok':>8} {'saved%':>7} {'$':>9} {'p50':>7} {'p90':>7} {'pass':>6}")
    for s in leaderboard(rows):
        if args.dataset and s["dataset"] != args.dataset:
            continue
        usd = "-" if s["dollars"] is None else f"{s['dollars']:.5f}"
        print(f"{s['dataset']:16} {s['mode'][:14]:14} {s['n']:4} {s['top_tokens'] if s['top_tokens'] is not None else '-':>8} "
              f"{f(s['saved_pct']):>7} {usd:>9} {f(s['p50_ms']):>7} {f(s['p90_ms']):>7} {f(None if s['pass_rate'] is None else 100 * s['pass_rate'], '%'):>6}"
              f"{'  (baseline)' if s['baseline'] else ''}{'  LOSS: ' + ','.join(s['bad']) if s['bad'] else ''}")
    return 0
