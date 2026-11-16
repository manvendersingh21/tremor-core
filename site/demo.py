"""Build site/demo.json: the saved results the page shows when no backend answers (a public link, GitHub Pages).

No number is typed here. Each value is read from a committed file (bench/*.md, bench/*.csv, .kiro/, tests/) and
carries the file it came from. If a report changes shape the build fails loudly (KeyError), like site/results.py.
Used by site/build.py (`python3 site/build.py` writes it, `--check` compares).
"""
import csv
import fnmatch
import json
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
MODEL = {"gpu-small": "qwen3:30b-instruct", "cloud-deepseek": "deepseek-ai/DeepSeek-V4.1-Flash"}  # docs/api.md ladder
HALL = ["observatory", "crypt", "ladder", "familiar", "workshop", "tower", "gpus", "guild", "gate", "ledger"]


def tracked(pattern):
    """Committed files matching a glob (so a local untracked file never changes the build). Falls back to the disk without git."""
    try:
        out = subprocess.run(["git", "ls-files", "--", pattern], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
        return sorted(ROOT / f for f in out if fnmatch.fnmatch(f, pattern))
    except (OSError, subprocess.CalledProcessError):
        return sorted(ROOT.glob(pattern))


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def _cells(line):
    return [c.strip().replace("**", "").replace("`", "") for c in line.strip().strip("|").split("|")]


def table(text, heading):
    """Rows (dicts by header) of the first markdown table after the line that starts with `heading`."""
    lines = text.splitlines()
    try:
        i = next(k for k, l in enumerate(lines) if l.startswith(heading))
    except StopIteration:
        raise KeyError(f"heading {heading!r} not found") from None
    rows = []
    for line in lines[i + 1:]:
        if line.startswith("|"):
            rows.append(_cells(line))
        elif rows or line.startswith("#"):
            break
    if len(rows) < 3:
        raise KeyError(f"no table after {heading!r}")
    return [dict(zip(rows[0], r)) for r in rows[2:]]


def rx(text, pattern):
    m = re.search(pattern, text)
    if not m:
        raise KeyError(f"pattern {pattern!r} not found")
    return m.groups() if len(m.groups()) > 1 else m.group(1)


def money(s):
    """'$12,060' -> 12060.0, '-$2,889 (-611%)' -> -2889.0"""
    m = re.search(r"(-?)\$([\d,]+(?:\.\d+)?)", s)
    if not m:
        raise KeyError(f"no dollar amount in {s!r}")
    return float(m.group(2).replace(",", "")) * (-1 if m.group(1) else 1)


def _f(v):
    return float(v) if v not in ("", None) else None


def _i(v):
    return int(float(v)) if v not in ("", None) else 0


# ---------- cost and scale: bench/results_company_cost.md ----------
def cost():
    src = "bench/results_company_cost.md"
    text = _read(src)
    per_1k = [{"tier": r["Tier"], "usd_per_1k": r["$ per 1,000 calls"], "pass": r["Pass on 301 coding tasks"],
               "source": r["Source"]} for r in table(text, "## Cost per 1,000 coding calls")]
    scale = {}
    for key, head in (("no_repeats", "### h = 0"), ("repeats_30", "### h = 30%")):
        rows = []
        for r in table(text, head):
            v = list(r.values())
            rows.append({"calls_a_day": int(v[0].replace(",", "")), "gpt55_only": money(v[1]), "cascade_gpt55": money(v[2]),
                         "saved_gpt55": v[3], "top763_only": money(v[4]), "cascade_763": money(v[5]), "saved_763": v[6],
                         "h200s": v[7]})
        scale[key] = rows
    return {"file": src, "per_1k": per_1k, "scale": scale,
            "idle_h200_day": rx(text, r"\*\*(\$[\d.]+) a day\*\*"),
            "pass_30b": rx(text, r"It failed (\d+ of \d+) coding tasks on the H200")}


# ---------- the saved run of the real stack: bench/results_backend.csv (COLD = first ask, WARM = the same again) ----------
def backend_rows():
    with open(BENCH / "results_backend.csv", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def prompts():
    out = {}
    for line in _read("bench/prompts.jsonl").splitlines():
        if line.strip():
            p = json.loads(line)
            out[p["id"]] = p
    return out


def events_first(r):
    """The /api/chat events of one COLD row, from its own columns (docs/api.md shapes). No column, no event."""
    tier = r["path"]
    ev = []
    if r["shared_ms"]:
        ev.append(["cache_shared", {"hit": False, "status": r["shared_status"] or "ok", "threshold": 0.97, "kind": None,
                                    "score": _f(r["shared_score"]), "guard": r["shared_guard"] or None, "ms": _f(r["shared_ms"])}])
    tin, tout = (_i(r["gpu_in"]), _i(r["gpu_out"])) if tier == "gpu-small" else (_i(r["big_in"]), _i(r["big_out"]))
    ev.append(["decide", {"tier": tier, "reason": "the tier that answered in the saved run"}])
    ev.append(["call", {"tier": tier, "model": MODEL.get(tier), "ok": True, "ms": _f(r["latency_ms"]), "tokens_in": tin, "tokens_out": tout}])
    if r["draft_conf"]:
        ev.append(["draft", {"tier": tier, "model": MODEL.get(tier), "confidence": _f(r["draft_conf"]), "gate": 0.95}])
    ev.append(["memory", {"op": "store", "stored": r["memory_stored"] == "True", "tier": tier, "tests_passed": None}])
    ev.append(["final", {"tier": tier, "model": MODEL.get(tier), "tokens_in": tin, "tokens_out": tout, "cached_tokens": 0,
                         "dollars": _f(r["dollars"]), "dollars_saved": _f(r["dollars_saved_est"]), "ms": _f(r["latency_ms"]),
                         "tokens_kept_off_big": _i(r["kept_off_big"]), "cache": None}])
    return ev


def events_repeat(r):
    kind = "exact" if r["tier_used"] == "exact_cache" else "semantic"
    return [["cache_shared", {"hit": True, "status": r["shared_status"] or "ok", "threshold": 0.97, "kind": kind,
                              "score": _f(r["shared_score"]), "guard": r["shared_guard"] or None, "ms": _f(r["shared_ms"])}],
            ["final", {"tier": r["tier_used"], "model": None, "tokens_in": 0, "tokens_out": 0, "cached_tokens": 0,
                       "dollars": 0.0, "dollars_saved": _f(r["dollars_saved_est"]), "ms": _f(r["latency_ms"]),
                       "tokens_kept_off_big": _i(r["kept_off_big"]), "cache": "shared"}]]


def short(answer):
    text = answer.replace("**", "").replace("###", "").strip().split("\n\n")[0].strip()
    return text if len(text) <= 260 else text[:257].rsplit(" ", 1)[0] + "…"


def chat(rows, ps):
    """Saved questions for the demo chat: the first ask is the COLD row, the repeat is the WARM row of the same prompt."""
    answers = json.loads(_read("bench/raw.json"))["answers"]
    by = {(r["pass"], r["id"]): r for r in rows}
    out = []
    for pid, p in ps.items():
        cold, warm, base, ans = by.get(("COLD", pid)), by.get(("WARM", pid)), by.get(("BASE", pid)), answers.get(f"A:{pid}")
        if not (cold and warm and base and ans) or cold["cache_source"] or not warm["cache_source"] or p["cat"] not in ("easy", "code"):
            continue
        a = short(ans["answer"])
        if len(a) > 260 or "```" in a:
            continue
        out.append({"id": pid, "q": p["prompt"], "answer": a, "first": events_first(cold), "repeat": events_repeat(warm),
                    "base_ms": _f(base["latency_ms"]), "base_tokens": _i(base["big_in"]) + _i(base["big_out"])})
        if len(out) == 6:
            break
    if len(out) < 3:
        raise KeyError("fewer than 3 saved chat examples")
    return {"examples": out, "source": "bench/results_backend.csv", "answers_from": "bench/raw.json",
            "note": "Route, time and tokens: the COLD pass (first ask) and the WARM pass (the same question again) of "
                    "bench/results_backend.csv. The answer text is the saved one from the first benchmark (bench/raw.json)."}


def stats(rows, ps):
    """A /api/stats-shaped block (docs/api.md) for the saved COLD + WARM passes: 120 calls of the real stack."""
    run = [r for r in rows if r["pass"] in ("COLD", "WARM")]
    hits = [r for r in run if r["cache_source"] == "shared"]
    tok = lambda r: _i(r["gpu_in"]) + _i(r["gpu_out"]) + _i(r["big_in"]) + _i(r["big_out"])  # noqa: E731
    by_tier, by_task, series = {}, {}, []
    for r in run:
        by_tier[r["tier_used"]] = by_tier.get(r["tier_used"], 0) + 1
        task = r["src"].split(":")[-1]
        t = by_task.setdefault(task, {"calls": 0, "tokens": 0, "cache_hits": 0, "tokens_saved": 0, "dollars_saved": 0.0})
        t["calls"] += 1; t["tokens"] += tok(r); t["cache_hits"] += r["cache_source"] == "shared"
        t["tokens_saved"] += _i(r["kept_off_big"]); t["dollars_saved"] = round(t["dollars_saved"] + (_f(r["dollars_saved_est"]) or 0), 8)
    for p in ("COLD", "WARM"):
        rs = [r for r in run if r["pass"] == p]
        series.append({"t": f"{p} pass", "calls": len(rs), "hits": sum(r["cache_source"] == "shared" for r in rs), "tokens": sum(map(tok, rs)), "tokens_saved": sum(_i(r["kept_off_big"]) for r in rs),
                       "dollars_saved": round(sum(_f(r["dollars_saved_est"]) or 0 for r in rs), 8),
                       "dollars_spent": round(sum(_f(r["dollars"]) or 0 for r in rs), 8)})
    exact = sum(r["tier_used"] == "exact_cache" for r in hits)
    g = {"calls": len(run), "calls_today": len(run), "tokens": sum(map(tok, run)), "tokens_today": sum(map(tok, run)),
         "cache_hits": {"exact": 0, "local": 0, "shared": len(hits)}, "hit_rate": round(len(hits) / len(run), 4),
         "cache": {"all_time": {"exact": exact, "cosine": len(hits) - exact, "false_hits": 0}, "today": {"exact": exact, "cosine": len(hits) - exact, "false_hits": 0}},
         "gpu_calls_avoided": len(hits), "big_calls_avoided": sum(r["tier_used"] != "top" for r in run),
         "dollars_saved": round(sum(_f(r["dollars_saved_est"]) or 0 for r in run), 8), "dollars_spent": round(sum(_f(r["dollars"]) or 0 for r in run), 8),
         "tokens_kept_off_big": sum(_i(r["kept_off_big"]) for r in run), "false_hits": 0, "by_tier": by_tier, "by_task": by_task,
         "series": {"daily": series, "hourly": series}}
    recent = []
    for r in [r for r in run if r["id"] in ps][::-1][:20]:
        steps = [dict(d, step=n) for n, d in (events_repeat(r) if r["cache_source"] else events_first(r))]
        fin = steps[-1]
        recent.append({"ts": None, "pass": r["pass"], "prompt": ps[r["id"]]["prompt"][:80], "task": r["src"].split(":")[-1],
                       "tier": r["tier_used"], "model": fin.get("model"), "cache": fin.get("cache"), "score": _f(r["shared_score"]),
                       "tokens_in": fin["tokens_in"], "tokens_out": fin["tokens_out"], "ms": _f(r["latency_ms"]),
                       "dollars": fin["dollars"], "dollars_saved": fin["dollars_saved"], "steps": steps})
    events = [{"tier_used": r["tier_used"], "tokens_saved": _i(r["kept_off_big"]), "dollars_saved": _f(r["dollars_saved_est"]) or 0,
               "latency_ms": _f(r["latency_ms"])} for r in run]
    return {"global": g, "session": g, "recent": recent, "events": events,
            "source": "bench/results_backend.csv (COLD + WARM passes, 2026-11-14)"}


# ---------- cache, bank, memory, speculative decoding ----------
def caches():
    be, vs, cc = _read("bench/results_backend.md"), _read("docs/vector-store.md"), _read("bench/results_company_cost.md")
    cold, cold_how, warm, warm_how = rx(be, r"Hit rate: COLD ([\d.]+) \(([^)]*)\), WARM ([\d.]+) \(([^)]*)\)")
    p50, p90 = rx(be, r"Lookup time[^:]*: p50 (\d+) ms, p90 (\d+) ms")
    rate, avoided = rx(vs, r"\| Postgres, shared \| [^|]+\| ([\d.]+) \| (\d+) \|")
    return [
        ["First ask (COLD), hit rate", f"{cold} ({cold_how})", "bench/results_backend.md"],
        ["Same questions again (WARM), hit rate", f"{warm} ({warm_how})", "bench/results_backend.md"],
        ["Wrong cache answers", rx(be, r"False hits: (\d+ of \d+) graded"), "bench/results_backend.md"],
        ["Lookup p50 / p90", f"{p50} / {p90} ms", "bench/results_backend.md"],
        ["3 repeats of 60 prompts", rx(cc, r"Cache: (\d+ of \d+ served in each of 3 repeats \([^)]*\), \d+ wrong)"), "bench/results_company_cost.md"],
        ["Second machine, shared cache", f"hit rate {rate}, {avoided} of 60 GPU calls avoided", "docs/vector-store.md"],
    ]


def bank():
    with open(BENCH / "results_bank.csv", newline="", encoding="utf-8") as fh:
        runs = [{k: (int(v) if re.fullmatch(r"\d+", v) else float(v)) for k, v in r.items()} for r in csv.DictReader(fh)]
    names = [r["Run"] for r in table(_read("bench/results_bank.md"), "## Table")]
    for r, n in zip(runs, names):
        r["name"] = n
    return {"file": "bench/results_bank.md", "runs": runs, "size": rx(_read("bench/results_bank.md"), r"Bank size: (\d+ pairs)")}


def spec():
    src = "bench/results_spec_modal.md"
    rows = table(_read(src), "## Phase A summary")
    return {"file": src, "title": "Phase A: Qwen3-235B-A22B verifier on 4x H100 (Modal)",
            "rows": [{"run": r["Run"], "how": r["Who drafts -> who checks"], "tok_s": r["tok/s"], "vs": r["vs 235B alone"],
                      "same": r["Same output as 235B alone"]} for r in rows]}


def memory():
    src = "bench/results_memory.md"
    text = _read(src)
    st = json.loads(rx(text, r"Stats: `(\{[^`]*\})`"))
    return [["Teacher pairs stored (Supabase)", str(st.get("teacher_pairs", st.get("solution"))), src],
            ["Concept graph nodes (Neo4j Aura)", str(sum(v for k, v in st.items() if k in ("problem", "solution", "concept", "pattern", "error"))), src],
            ["Concept graph edges (Neo4j Aura)", str(st["edges"]), src],
            ["Solved-problem bank", rx(_read("bench/results_bank.md"), r"Bank size: (\d+ pairs)"), "bench/results_bank.md"]]


# ---------- how Kiro built it: counted from .kiro/, powers/ and tests/ ----------
def kiro():
    steering = [p.stem for p in tracked(".kiro/steering/*.md")]
    specs = [p.parent.name for p in tracked(".kiro/specs/*/requirements.md")]
    done = total = 0
    for p in tracked(".kiro/specs/*/tasks.md"):
        t = p.read_text(encoding="utf-8")
        done += len(re.findall(r"^\s*- \[x\]", t, re.M)); total += len(re.findall(r"^\s*- \[[ x]\]", t, re.M))
    ears = sum(len(re.findall(r"\bSHALL\b", p.read_text(encoding="utf-8"))) for p in tracked(".kiro/specs/*/requirements.md"))
    hooks = []
    for p in tracked(".kiro/hooks/*.json"):
        d = json.loads(p.read_text(encoding="utf-8"))
        hooks += [h["name"] for h in d.get("hooks", [])] or [d.get("name") or p.stem]
    agents = [p.stem for p in tracked(".kiro/agents/*.json")]
    tools = sorted(set(re.findall(r"^def (chimera_\w+)\(", _read("apps/kiro-trimmer/mcp_server.py"), re.M)))
    servers = sorted(json.loads(_read("powers/chimera/workspace-mcp.json"))["mcpServers"])
    power = json.loads(_read("powers/chimera/plugin.json"))["name"]
    skills = sorted({p.relative_to(ROOT / "powers/chimera/skills").parts[0] for p in tracked("powers/chimera/skills/*/*")})
    props_files = tracked("tests/test_props_*.py")
    props = sum(len(re.findall(r"^\s*@given\(", f.read_text(encoding="utf-8"), re.M)) for f in props_files)
    xfail = sum(len(re.findall(r"xfail\(", f.read_text(encoding="utf-8"))) for f in props_files)
    found = int(rx(_read("docs/handoff/property-tests.md"), r"## Failures found \((\d+)\)"))
    v2 = _read("bench/results_backend_v2.md")
    before, after = rx(v2, r"\| (\d+) xfailed \| \*\*(\d+) xfailed\*\*")
    handoffs = [p.stem for p in tracked("docs/handoff/*.md")]
    B = "https://github.com/manvendersingh21/tremor-core/blob/dev/"
    posters = [
        {"title": "Steering", "big": f"{len(steering)} files", "lines": [", ".join(steering) + ".", "Rules every Kiro chat loads: one URL, real numbers only, secrets stay in .env."], "src": [".kiro/steering/", ".kiro/steering"]},
        {"title": "Specs", "big": f"{len(specs)} specs", "lines": [f"{ears} EARS requirements (SHALL). {done} of {total} tasks ticked.", ", ".join(specs) + "."], "src": [".kiro/specs/", ".kiro/specs"]},
        {"title": "Hooks", "big": f"{len(hooks)} hooks", "lines": [", ".join(hooks) + ".", "Secret scan on stop and before every commit; tests on save."], "src": [".kiro/hooks/", ".kiro/hooks"]},
        {"title": "Custom agents", "big": f"{len(agents)} agents", "lines": [", ".join(agents) + ".", "Each one can write only its own folders and never reads .env."], "src": [".kiro/agents/", ".kiro/agents"]},
        {"title": "MCP", "big": f"{len(tools)} tools", "lines": [", ".join(tools) + ": the router as an MCP server.", f"{len(servers)} MCP servers in the workspace config, all read-only for data."], "src": ["apps/kiro-trimmer/mcp_server.py", "apps/kiro-trimmer/mcp_server.py"]},
        {"title": "Kiro Power", "big": power, "lines": [f"{len(skills)} skills: {', '.join(skills)}.", "One folder to install the router into any Kiro workspace."], "src": ["powers/chimera/", "powers/chimera"]},
        {"title": "Kiro Crew", "big": f"{len(handoffs)} handoffs", "lines": ["A backend chat and a frontend chat built this, each owning its folders.", f"Finished work items left {len(handoffs)} handoff notes in docs/handoff/."], "src": ["docs/handoff/", "docs/handoff"]},
        {"title": "Property tests", "big": f"{props} properties", "lines": [f"Hypothesis tried to break {props} rules in {len(props_files)} files, 200 examples each.", f"{found} real bugs found, {found - int(after)} fixed: {before} xfailed then {after}. Now {xfail} xfail markers left."], "src": ["docs/handoff/property-tests.md", "docs/handoff/property-tests.md"]},
    ]
    return {"steering": steering, "specs": specs, "spec_tasks": [done, total], "ears": ears, "hooks": hooks, "agents": agents,
            "mcp_tools": tools, "mcp_servers": servers, "power": power, "skills": skills, "properties": props,
            "property_files": len(props_files), "bugs_found": found, "bugs_fixed": found - int(after), "xfail_left": xfail,
            "handoffs": len(handoffs), "posters": posters, "base": B}


# ---------- the guided tour: one stop per room, about 3 minutes, also the demo video script ----------
def tour(d):
    g, c, k, s = d["stats"]["global"], d["cost"], d["kiro"], d["spec"]["rows"]
    warm = [r for r in d["stats"]["global"]["series"]["daily"] if r["t"].startswith("WARM")][0]
    one_m = [r for r in c["scale"]["no_repeats"] if r["calls_a_day"] == 1_000_000][0]
    per = {r["tier"]: r["usd_per_1k"] for r in c["per_1k"]}
    eagle = [r for r in s if r["run"].startswith("Same box: EAGLE")][0]
    cross = [r for r in s if r["run"] == "Cross-box, 30B drafter, K=4"][0]
    b2 = [r for r in d["bank"]["runs"] if r["run"] == 2][0]
    h200 = [v for t, v in per.items() if t.startswith("30B on one H200, busy 100% of the day")][0]
    v100 = [v for t, v in per.items() if t.startswith("30B on the shared V100")][0]
    top = [v for t, v in per.items() if t.startswith("DeepSeek")][0]
    gpt = [v for t, v in per.items() if t.startswith("GPT-5.5")][0]
    cache = {r[0]: r[1] for r in d["cache"]}
    s763 = money(one_m["saved_763"])
    vs763 = (f"Against the cheap 763B we do not save at that volume: the ladder costs ${-s763:,.0f} a month more." if s763 < 0
             else f"Against the 763B it saves ${s763:,.0f} a month.")
    stops = [
        {"at": "landing", "secs": 7, "say": "Good evening. I am Count Cuspid. This castle sends every AI question to the cheapest helper that can answer it. Come, I will walk you in."},
        {"at": "walk", "secs": 5, "say": "The iron gates open as we arrive, and the great door too. Four seconds from the road to the hall."},
        {"at": "hall", "secs": 10, "say": f"The Great Hall. The board shows the saved run of the real stack: {g['calls']} calls, {round(g['hit_rate'] * 100)}% answered from the cache, {g['tokens_kept_off_big']:,} tokens kept off the big model."},
        {"room": "observatory", "secs": 14, "say": f"The Observatory counts every call. The second time the same {warm['calls']} questions came in, {warm['hits']} were served from the cache with no model, and the ladder spent ${warm['dollars_spent']:.5f}."},
        {"room": "crypt", "secs": 13, "say": f"The Crypt is the cache in Supabase. Asked again, the hit rate was {cache['Same questions again (WARM), hit rate'].split()[0]}. A lookup takes {cache['Lookup p50 / p90'].split(' /')[0]} ms. {cache['Wrong cache answers']} graded cache answers were wrong."},
        {"room": "ladder", "secs": 14, "say": f"The Ladder climbs one rung at a time: cache, then our own 30B, then the 763B. Per 1,000 coding calls the 763B costs {top}, GPT-5.5 costs {gpt}. The bank of solved problems served {b2['served']} of {b2['problems']} repeats, {b2['wrong_caught']} wrong."},
        {"room": "familiar", "secs": 9, "say": "The Familiar is a small model for your phone. It is written, but no phone has run it yet. I will not pretend otherwise."},
        {"room": "workshop", "secs": 18, "say": f"The Workshop shows how Kiro built this castle: {len(k['steering'])} steering files, {len(k['specs'])} specs, {len(k['hooks'])} hooks, {len(k['agents'])} custom agents, {len(k['mcp_tools'])} MCP tools and a Power. Hypothesis tried {k['properties']} property tests and found {k['bugs_found']} real bugs. {k['bugs_fixed']} are fixed."},
        {"room": "tower", "secs": 12, "say": f"The Tower holds the biggest models. We tried speculative decoding on Modal: EAGLE-3 in the same box ran {eagle['vs']} as fast, but a drafter on another box ran at only {cross['vs']}. We show both."},
        {"room": "gpus", "secs": 12, "say": f"The Manor is our own GPU. A 30B on an H200 kept busy costs {h200} per 1,000 calls. On the shared V100, one call at a time, it costs {v100}."},
        {"room": "guild", "secs": 9, "say": "The Guild is for companies: an OpenAI-style gateway, keys per tenant, metrics for Prometheus. Change one address and one key."},
        {"room": "gate", "secs": 9, "say": "The Gate: four commands and it runs on your machine. The tests need no models and no keys."},
        {"room": "ledger", "secs": 20, "chart": True, "say": f"And the bill. At 1 million coding calls a day, GPT-5.5 alone costs ${one_m['gpt55_only']:,.0f} a month. With the cache, the bank and our 30B first: ${one_m['cascade_gpt55']:,.0f}, {one_m['saved_gpt55'].split('(')[1].rstrip(')')} less. {vs763} Every number here comes from a file. Good night."},
    ]
    assert [x["room"] for x in stops if "room" in x] == HALL, "one tour stop per hall door, in hall order"
    return stops


def build_dict():
    rows, ps = backend_rows(), prompts()
    d = {"built_from": ["bench/results_backend.csv", "bench/results_backend.md", "bench/results_company_cost.md", "bench/results_bank.csv",
                        "bench/results_bank.md", "bench/results_spec_modal.md", "bench/results_memory.md", "docs/vector-store.md",
                        "bench/raw.json", "bench/prompts.jsonl", ".kiro/", "powers/chimera/", "tests/test_props_*.py"],
         "stats": stats(rows, ps), "chat": chat(rows, ps), "cost": cost(), "cache": caches(), "bank": bank(), "spec": spec(),
         "storage": memory(), "kiro": kiro()}
    d["tour"] = tour(d)
    return d


def build():
    return json.dumps(build_dict(), indent=1, ensure_ascii=False) + "\n"


def tour_script(d=None):
    """The tour as a video script (site/docs/tour_script.md), written from the same stops the page plays."""
    d = d or build_dict()
    t, out = 0, ["# The guided tour: demo video script", "",
                 "Written by `python3 site/build.py` from `site/demo.json` (the same stops the page plays: press T or the Tour button).",
                 "Every number is read from the file named in `site/demo.json`.", "", "| Time | Where | The Count says |", "|---|---|---|"]
    for s in d["tour"]:
        where = s.get("room") or s["at"]
        out.append(f"| {t // 60}:{t % 60:02d} | {where} | {s['say']} |")
        t += s["secs"]
    out += ["", f"Total: {t // 60} min {t % 60:02d} s of narration, plus the room-door clips (played fast during the tour).", ""]
    return "\n".join(out)
