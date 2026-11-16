"""Driver for the Modal speculative-decoding runs (deploy/modal/spec_modal.py, jobs in deploy/modal/spec_models.py).
Raw results stay in the git-ignored bench/.scratch/spec_modal/; the committed report is bench/results_spec_modal.md.

  python bench/run_spec_modal.py prompts             # offline: 48 measured prompts + 2 warm-up prompts
  python bench/run_spec_modal.py download KEY,KEY    # CPU-only weight download to the Modal volumes, then stop-and-prove
  python bench/run_spec_modal.py job JOB             # one `modal run` (ephemeral app chimera-spec-...), then stop-and-prove
  python bench/run_spec_modal.py stop JOB            # stop that job's app by ID and save the proof
  python bench/run_spec_modal.py report              # write the generated tables into bench/results_spec_modal.md

Every job ends with `modal app list` saved to bench/.scratch/spec_modal/applist_<job>.txt, also when it fails.
"""
import json
import os
import pathlib
import random
import re
import statistics
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "bench" / ".scratch" / "spec_modal"
MODAL = str(ROOT / ".venv" / "bin" / "modal")
REPORT = ROOT / "bench" / "results_spec_modal.md"
sys.path[:0] = [str(ROOT / "bench"), str(ROOT / "deploy" / "modal")]
from spec_models import DRAFTERS, JOBS, MODELS, family  # noqa: E402

APP = "chimera-spec-modal"
# (file, field, value, how many): 28 code + 20 chat, reasoning and short answers
MIX = [("bench/cost_case/tasks.jsonl", "difficulty", "trivial", 10), ("bench/cost_case/tasks.jsonl", "difficulty", "everyday", 8),
       ("bench/cost_case/tasks.jsonl", "difficulty", "hard", 4), ("bench/datasets/suite.jsonl", "source", "humaneval", 3),
       ("bench/datasets/suite.jsonl", "source", "mbpp", 3), ("bench/datasets/suite.jsonl", "source", "dolly", 10),
       ("bench/datasets/suite.jsonl", "source", "gsm8k", 5), ("bench/datasets/suite.jsonl", "source", "mmlu", 5)]
KIND = {"dolly": "chat", "gsm8k": "math", "mmlu": "short"}
RATES = {"H200": 4.54, "L40S": 1.95}  # $/GPU-hour, `modal billing rates` 2026-11-15


def pick_prompts(seed: int = 7) -> dict:
    rnd, out, warm = random.Random(seed), [], []
    for f, key, val, n in MIX:
        rows = [json.loads(line) for line in (ROOT / f).read_text().splitlines() if line.strip()]
        rows = [r for r in rows if r.get(key) == val]
        picked = rnd.sample(rows, n + 1)  # one extra per group feeds the warm-up pool
        for r in picked[:n]:
            out.append({"id": r["id"], "kind": KIND.get(val, "code"), "messages": [{"role": "user", "content": r["prompt"]}]})
        warm.append({"id": "warm-" + picked[n]["id"], "kind": "warm", "messages": [{"role": "user", "content": picked[n]["prompt"]}]})
    return {"prompts": out, "warm": [warm[0], warm[5]]}  # one code, one chat


# ---------- Modal: run, stop, prove ----------
def modal_json(*args):
    return json.loads(subprocess.run([MODAL, *args, "--json"], capture_output=True, text=True, check=True).stdout)


def live_apps(app: str, rows=None) -> list[dict]:
    """Apps with this exact name that are not stopped. `modal app list --json` keys are lower case:
    app_id, description, state, tasks, created_at, stopped_at."""
    rows = modal_json("app", "list") if rows is None else rows
    return [a for a in rows if a.get("description") == app and a.get("state") != "stopped"]


def ensure_stopped(tag: str, app: str) -> int:
    """Stop every live app with this exact name by ID, then save `modal app list` as proof. Returns how many are live.
    Only our own names are passed in, so the other chats' apps are never touched."""
    assert app.startswith("chimera-spec-"), app
    live = []
    for _ in range(12):
        live = live_apps(app)
        if not live:
            break
        for a in live:
            if a["state"] != "stopping":
                subprocess.run([MODAL, "app", "stop", "-y", a["app_id"]], check=False)
        time.sleep(5)
    rows = modal_json("app", "list")
    ours = [a for a in rows if a.get("description") == app]
    table = subprocess.run([MODAL, "app", "list"], capture_output=True, text=True).stdout
    proof = (f"{time.strftime('%Y-%m-%d %H:%M:%S %Z')}  live {app} apps: {len(live)}\n"
             + "".join(f"{a['app_id']} {a['description']} {a['state']} created {a['created_at']} stopped {a['stopped_at']}\n" for a in ours)
             + "\n" + table)
    (OUT / f"applist_{tag}.txt").write_text(proof)
    print(proof, flush=True)
    return len(live)


def run_logged(tag: str, app: str, cmd: list[str], env: dict) -> int:
    log, code = OUT / f"job_{tag}.log", 1
    try:
        with log.open("a") as fh:
            fh.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(cmd[1:])}\n")
            fh.flush()
            code = subprocess.run(cmd, env=env, stdout=fh, stderr=subprocess.STDOUT, cwd=ROOT).returncode
    finally:  # success, failure or Ctrl-C: stop first, then prove it
        live = ensure_stopped(tag, app)
    print(f"{tag}: exit {code}, live {app} apps after stop: {live}, log {log}", flush=True)
    return code or live


def job(name: str) -> int:
    env = {**os.environ, "SPEC_JOB": name}
    return run_logged(name, JOBS[name]["app"], [MODAL, "run", "-q", str(ROOT / "deploy" / "modal" / "spec_modal.py")], env)


def download(keys: str, tag: str = "") -> int:
    """CPU-only weight download; tag gives the batch its own app name (chimera-spec-download-<tag>)."""
    app = "chimera-spec-download" + (f"-{tag}" if tag else "")
    env = {**os.environ, "SPEC_DL_TAG": tag}
    return run_logged(f"download{('_' + tag) if tag else ''}", app,
                      [MODAL, "run", "-q", str(ROOT / "deploy" / "modal" / "spec_download.py"), "--keys", keys], env)


# ---------- offline report ----------
def lossless(base: dict, run: dict, eos=None) -> tuple[int, int]:
    from spec_modal_core import EOS, first_diff

    a = {r["id"]: r["out"] for r in base["rows"]}
    cmp = [(a[r["id"]], r["out"]) for r in run["rows"] if r["id"] in a]
    return sum(first_diff(x, y, eos or EOS) == -1 for x, y in cmp), len(cmp)


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * q))] if xs else float("nan")


def summarize(run: dict) -> dict:
    rows = run["rows"]
    toks, wall = sum(len(r["out"]) for r in rows), sum(r["wall_s"] for r in rows)
    s = {"tok_s": toks / wall, "tokens": toks, "wall_s": wall,
         "median_tok_s": statistics.median(len(r["out"]) / r["wall_s"] for r in rows if r["wall_s"] > 0)}
    for kind in ("code", "chat", "math", "short"):
        sub = [r for r in rows if r.get("kind") == kind]
        if sub:
            s[f"tok_s_{kind}"] = sum(len(r["out"]) for r in sub) / sum(r["wall_s"] for r in sub)
    if "rounds" in rows[0]:
        rounds, drafted, acc = (sum(r[k] for r in rows) for k in ("rounds", "drafted", "accepted"))
        misses = sum(r["misses"] for r in rows)
        s.update(alpha=acc / drafted if drafted else 0, alpha_tested=acc / (acc + misses) if acc + misses else 0,
                 tok_per_round=toks / rounds, k_mean=statistics.mean(k for r in rows for k in r["ks"]),
                 draft_ms_per_round=sum(r["draft_ms"] for r in rows) / rounds,
                 free_accepted=sum(r["free_accepted"] for r in rows), reused=sum(r["reused"] for r in rows))
    if run.get("rtt_ms"):
        net = [a - b for a, b in zip(run["rtt_ms"], run["server_ms"])]
        s.update(rtt_p50_ms=pct(run["rtt_ms"], 0.5), rtt_p90_ms=pct(run["rtt_ms"], 0.9),
                 server_p50_ms=pct(run["server_ms"], 0.5), net_p50_ms=pct(net, 0.5))
    c = (run.get("spec_counters") or {}).get("run_delta") or {}
    acc_k = next((k for k in c if k.endswith("num_accepted_tokens_total")), None)
    drf_k = next((k for k in c if k.endswith("num_draft_tokens_total")), None)
    n_k = next((k for k in c if k.endswith("num_drafts_total")), None)
    if acc_k and drf_k and c[drf_k]:
        s["server_acceptance"] = c[acc_k] / c[drf_k]
        if n_k and c[n_k]:
            s["server_mean_accept_len"] = 1 + c[acc_k] / c[n_k]
    return s


def load_runs() -> dict:
    return {p.stem: json.loads(p.read_text()) for p in sorted(OUT.glob("*.json"))
            if p.stem not in ("prompts",) and not p.stem.startswith("meta_") and not p.stem.endswith(".error")}


def f1(x, nd=1):
    return "" if x is None or (isinstance(x, float) and x != x) else f"{x:.{nd}f}"


def short(key: str) -> str:
    """Qwen/Qwen3-235B-A22B-Instruct-2507-FP8 -> Qwen3-235B-A22B."""
    name = MODELS[key]["repo"].split("/")[-1]
    for cut in ("-Instruct-2507", "-Instruct", "-FP8"):
        name = name.replace(cut, "")
    return name


MODE_LABEL = {"ngram": "n-gram (prompt lookup)", "draft_q3_4b": "Qwen3-4B draft model", "draft_q35_4b": "Qwen3.5-4B draft model",
              "eagle_q3_235b": "EAGLE-3 head", "eagle_q3_30b": "EAGLE-3 head", "eagle_q3c_480b": "EAGLE-3 head",
              "eagle_q35_397b": "EAGLE-3 head", "mtp2": "built-in MTP, 2 tokens"}


def describe(plan: dict, big: str) -> tuple[str, str]:
    """(who drafts -> who verifies, method) labels for a plan."""
    if plan["mode"] == "big_alone":
        same = plan["name"].split("_big_", 1)[-1] if "_big_" in plan["name"] else ""
        if same in MODE_LABEL:
            return f"inside {short(big)}", f"same box: {MODE_LABEL[same]}"
        return f"{short(big)} alone", "no speculation" + (" (repeat)" if plan["name"].endswith("_rep") else "")
    d = DRAFTERS[plan["drafter"]]
    lab = short(d["model"])
    if d["mode"] != "plain":
        lab = f"{MODE_LABEL[d['mode']].split(',')[0].replace(' draft model', '')} -> {lab}"
    if plan["mode"] == "draft_alone":
        return f"{lab} alone (L40S)", "no speculation" + (" (same-box helper on the drafter)" if d["mode"] != "plain" else "")
    how = "Spec+ (adaptive K, pipelined, free drafts)" if plan.get("adaptive") else f"plain spec, K={plan.get('k', 4)}"
    if plan.get("extra_rtt_ms"):
        how += f", +{plan['extra_rtt_ms']} ms added per round"
    return f"{lab} (L40S) -> {short(big)}", how


def project(run: dict, net_ms: float) -> float:
    """tok/s if each round's network time were net_ms: measured wall - measured network + rounds x net_ms.
    shortcut: assumes draft and server time stay the same; a pipelined pre-draft hidden behind a long round trip
    would show up again at a short one, so the Spec+ projection is optimistic."""
    rows = run["rows"]
    toks, wall, rounds = sum(len(r["out"]) for r in rows), sum(r["wall_s"] for r in rows), sum(r["rounds"] for r in rows)
    net = sum(a - b for a, b in zip(run["rtt_ms"], run["server_ms"])) / 1e3
    return toks / (wall - net + rounds * net_ms / 1e3)


def why_not(name: str) -> str:
    """Plain reason a plan has no result (no account ids in the committed report)."""
    err = OUT / f"{name}.error.json"
    if not err.exists():
        return "not reached"
    e = json.loads(err.read_text())["error"]
    if "is disabled" in e or "spend limit" in e:
        return "stopped: the account's credits ran out"
    return re.sub(r"\b(ac|ap|fu|ta|in)-[A-Za-z0-9]{6,}", "<id>", e)[:120].replace("|", "/")


def trace_stats(run: dict) -> dict:
    """From the per-round trace: share of rounds that fell back to full scoring, and big-box ms with and without."""
    t = run.get("trace") or []
    if not t:
        return {}
    cols = run.get("trace_cols") or ["n_ctx", "n_draft", "accepted", "server_ms", "round_trip_ms", "cache_hit", "fallback"]
    rows = [dict(zip(cols, x)) for x in t]
    fast = [x["server_ms"] for x in rows if not x["fallback"]]
    full = [x["server_ms"] for x in rows if x["fallback"]]
    new = [x["n_ctx"] + x["n_draft"] - x["cache_hit"] for x in rows if x["cache_hit"] is not None and not x["fallback"]]
    return {"fallback_share": len(full) / len(rows), "server_fast_p50": pct(fast, 0.5), "server_full_p50": pct(full, 0.5),
            "new_tokens_p50": pct(new, 0.5)}


def job_tables(job: str, runs: dict) -> str:
    cfg = JOBS[job]
    big = cfg["big"]
    eos = family(cfg["tok"])["eos"]
    plans = cfg["plans"] + [p for j in cfg.get("report_with", []) for p in JOBS[j]["plans"]]  # follow-up jobs
    names = [p["name"] for p in plans if p["mode"] in ("big_alone", "draft_alone", "spec")]
    tag = names[0].split("_")[0]
    base = runs.get(f"{tag}_big_alone")
    bs = summarize(base) if base else None
    n_prompts = len(base["rows"]) if base else 0
    mt = base["plan"].get("max_tokens", 256) if base else 256
    speed = [f"Speed, {n_prompts} prompts, greedy, max {mt} new tokens, one request at a time "
             "(tok/s = all output tokens / all wall time; median = median of the per-prompt tok/s):", "",
             "| Run | Who drafts -> who checks | Method | tok/s | median | vs big alone | code tok/s | chat tok/s | alpha (accepted / drafted) | tokens per round | same output as big alone |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    rounds = ["Where a cross-box round goes (medians per round; network = round trip minus the big box's own time; "
              "full-scoring rounds = the cache-reading verify failed and the round was scored again from scratch):", "",
              "| Run | rounds | draft ms | network ms | big box ms | round trip p50 / p90 ms | bare call (ping) p50 ms | mean K | full-scoring rounds | big box ms cached / full | tok/s at 20 ms network (projected) | tok/s at 0 ms (projected) |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    missing = []
    for n in names:
        r = runs.get(n)
        if not r or not r.get("rows"):
            missing.append(f"`{n}` ({why_not(n)})")
            continue
        s = summarize(r)
        who, how = describe(r["plan"], big)
        rel = f"{s['tok_s'] / bs['tok_s']:.2f}x" if bs and n != f"{tag}_big_alone" else ""
        alpha = f1(s.get("alpha"), 2) if "alpha" in s else (f1(s.get("server_acceptance"), 2) + " (vLLM)" if "server_acceptance" in s else "")
        tpr = f1(s.get("tok_per_round"), 2) if "tok_per_round" in s else (f1(s.get("server_mean_accept_len"), 2) + " (vLLM)" if "server_mean_accept_len" in s else "")
        same = ("%d/%d" % lossless(base, r, eos)) if base and n != f"{tag}_big_alone" and r["plan"]["mode"] != "draft_alone" else ""
        speed.append(f"| `{n}` | {who} | {how} | {f1(s['tok_s'])} | {f1(s['median_tok_s'])} | {rel} | "
                     f"{f1(s.get('tok_s_code'))} | {f1(s.get('tok_s_chat'))} | {alpha} | {tpr} | {same} |")
        if r["plan"]["mode"] == "spec" and r.get("rtt_ms"):
            rows_n = sum(x["rounds"] for x in r["rows"])
            ping = f1(pct(r["ping_ms"], 0.5), 0) if r.get("ping_ms") else ""
            ts = trace_stats(r)
            fb = f"{ts['fallback_share']:.0%}" if ts else "not traced"
            cf = f"{f1(ts.get('server_fast_p50'), 0)} / {f1(ts.get('server_full_p50'), 0)}" if ts else ""
            rounds.append(f"| `{n}` | {rows_n} | {f1(s['draft_ms_per_round'], 0)} | {f1(s['net_p50_ms'], 0)} | "
                          f"{f1(s['server_p50_ms'], 0)} | {f1(s['rtt_p50_ms'], 0)} / {f1(s['rtt_p90_ms'], 0)} | {ping} | "
                          f"{f1(s['k_mean'])} | {fb} | {cf} | {f1(project(r, 20))} | {f1(project(r, 0))} |")
    out = ["\n".join(speed)]
    if len(rounds) > 4:
        out.append("\n".join(rounds))
    if missing:
        out.append("Not measured in this account: " + ", ".join(missing) + ".")
    inner = []  # a drafter with its own same-box helper must still write exactly what the drafter writes alone
    for a, b in ((f"{tag}_chain_alone", f"{tag}_mid_alone"), (f"{tag}_mideagle_alone", f"{tag}_mid_alone")):
        if a in runs and b in runs:
            same, tot = lossless(runs[b], runs[a], eos)
            inner.append(f"`{a}` vs `{b}`: {same}/{tot} identical")
    if inner:
        out.append("Same-box helper inside the drafter box (must not change the drafter's own output): " + "; ".join(inner) + ".")
    if f"{tag}_rescore" in runs:
        rs = runs[f"{tag}_rescore"]["rows"]
        flips = [f for x in rs for f in x["flips"]]
        toks = sum(x["n"] for x in rs)
        ties = {t: sum(x["ties"][str(t)] if str(t) in x["ties"] else x["ties"].get(t, 0) for x in rs) for t in (0.05, 0.1, 0.5)}
        gaps = sorted(round(f[3], 3) for f in flips)
        out.append(f"Root-cause check: the big model's own {toks} output tokens (big alone, {len(rs)} answers), scored "
                   f"again in one forward pass over the whole answer (the shape a verify round uses). At {len(flips)} "
                   f"positions in {sum(1 for x in rs if x['flips'])} answers the one-pass top-1 is not the token the "
                   f"one-token-at-a-time decode wrote; how far the decoded token is below that top-1 there (nats): "
                   f"{gaps if gaps else 'none'}. Positions whose top-1 and top-2 are within 0.05 / 0.1 / 0.5 nats: "
                   f"{ties[0.05]} / {ties[0.1]} / {ties[0.5]} of {toks}.")
    marg = [x for k in sorted(runs) if k.startswith(f"{tag}_margins") for x in runs[k]["rows"]]
    if marg:
        gaps = sorted(round(x["top2"][0][1] - x["top2"][1][1], 3) for x in marg if len(x.get("top2", [])) == 2)
        agree = sum(x["top2"][0][0] == x["other_tok"] for x in marg if x.get("top2"))
        out.append(f"Every output that differs from the big model alone, checked at its first different token: {len(marg)} "
                   f"cases. At {agree} of them the big model's own top-1 token, scored in one forward pass, is the token "
                   f"the other run wrote, not the one big alone wrote. Top-1 minus top-2 logprob gap there (nats): "
                   f"{gaps if gaps else 'none'}; {sum(g < 0.5 for g in gaps)} of {len(gaps)} are under 0.5.")
    meta = json.loads((OUT / f"meta_{job}.json").read_text()) if (OUT / f"meta_{job}.json").exists() else None
    if meta and meta.get("big_first_health_s"):
        starts = meta.get("health_end", {}).get("starts") if isinstance(meta.get("health_end"), dict) else None
        starts = starts or meta.get("big_health", {}).get("starts", [])
        st = ", ".join(f"{s['mode']} {s['start_s']:.0f} s" for s in starts)
        sw = ", ".join(f"{s['mode']} {s['s']:.0f} s" for s in meta.get("switches", []))
        dr = ", ".join(f"{k} {v.get('boot_s'):.0f} s" for k, v in meta.get("drafters", {}).items() if v.get("boot_s"))
        h = meta.get("big_health", {})
        where = h.get("where", {})
        gpus = h.get("gpus_seen") or []
        gpu = f"{len(gpus)}x {gpus[0].split(',')[0].replace('NVIDIA ', '')}" if gpus else cfg["gpu"]
        dwhere = {v.get("where", {}).get("MODAL_REGION") for v in meta.get("drafters", {}).values()}
        out.append(f"Hardware and cold starts (not in any number above): big box {gpu}, region {where.get('MODAL_REGION')}; "
                   f"drafter boxes 1x L40S, regions {sorted(x for x in dwhere if x)}. Big box first answer "
                   f"{meta['big_first_health_s']:.0f} s after the job started (container, weights from the volume, vLLM "
                   f"start, warm-up, self-test; first vLLM start {st}). Restarts for same-box modes: {sw or 'none'}. "
                   f"Drafter boxes boot: {dr}. Job wall time {(meta.get('t_end', meta['t0']) - meta['t0']) / 60:.0f} min.")
    return "\n\n".join(out)


def write_report():
    runs = load_runs()
    text = REPORT.read_text() if REPORT.exists() else ""
    for job in JOBS:
        block = f"<!-- tables:{job} -->"
        if block not in text:
            continue
        new = f"{block}\n{job_tables(job, runs)}\n<!-- /tables:{job} -->"
        text = re.sub(re.escape(block) + r".*?" + re.escape(f"<!-- /tables:{job} -->"), lambda _: new, text, flags=re.S)
    REPORT.write_text(text)
    print("wrote", REPORT)


def billing(app_ids: list[str], since: str = "today") -> dict:
    """Billed $ per app from `modal billing report` (hourly buckets; the current hour shows up later)."""
    rows = modal_json("billing", "report", "--for", since, "--resolution", "h", "--show-resources")
    out = {}
    for r in rows:
        if r.get("object_id") in app_ids:
            out.setdefault(r["object_id"], {}).setdefault(r["resource"], 0.0)
            out[r["object_id"]][r["resource"]] += float(r["cost"])
    return out


def main(argv):
    OUT.mkdir(parents=True, exist_ok=True)
    cmd = argv[1] if len(argv) > 1 else "prompts"
    if cmd == "prompts":
        ps = pick_prompts()
        (OUT / "prompts.json").write_text(json.dumps(ps))
        print(len(ps["prompts"]), "prompts,", sum(p["kind"] == "code" for p in ps["prompts"]), "code,",
              len(ps["warm"]), "warm-up")
    elif cmd == "job":
        sys.exit(job(argv[2]))
    elif cmd == "download":
        sys.exit(download(argv[2], argv[3] if len(argv) > 3 else ""))
    elif cmd == "stop":
        app = "chimera-spec-download" if argv[2] == "download" else JOBS[argv[2]]["app"]
        sys.exit(ensure_stopped(argv[2], app))
    elif cmd == "report":
        write_report()
    elif cmd == "billing":
        ids = [a["app_id"] for a in modal_json("app", "list") if a.get("description", "").startswith("chimera-spec-")]
        print(json.dumps(billing(ids, argv[2] if len(argv) > 2 else "today"), indent=1))


if __name__ == "__main__":
    main(sys.argv)
