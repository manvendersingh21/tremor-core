"""Report for bench/run_backend.py: writes bench/results_backend.md and .csv from the scratch rows."""
from __future__ import annotations

import csv
import json

from run_backend import ORDER, PAIRS, ROOT, acc, load, pct


def report(verdict: str = "") -> None:
    by = load()
    big = lambda r: r["big_in"] + r["big_out"]  # noqa: E731
    tot = lambda m, f: sum(f(r) for r in by[m])  # noqa: E731
    hit = lambda r: bool(r["cache_source"])  # noqa: E731
    calls_big = lambda m: sum(1 for r in by[m] if big(r))  # noqa: E731
    n = len(by["BASE"]) or len(by["COLD"])
    L = ["# Backend end to end: production path, real stack", "",
         f"Date 2026-11-14. {n} prompts: 30 from `bench/prompts.jsonl` (easy, paraphrase, repeat, small and heavy code) and 30 "
         "from `bench/datasets/suite.jsonl` (10 MMLU, 10 GSM8K, 5 HumanEval, 5 MBPP). One run per pass, no repeats.", "",
         "Path under test: `config.build_router` with `use_pool`, the same router object `/api/chat` and the gateway use. "
         "Ladder: Supabase cache (exact hash, then pgvector cosine >= 0.97, guard on; the only answer cache; app role under RLS) -> "
         "GPU Qwen3-30B (Ollama on a V100 reached through a tunnel to your GPU box; gate: mean token probability >= 0.95 "
         "from Ollama logprobs) -> Crusoe DeepSeek-V4.1-Flash 763B (thinking off). No Mac 3B. Modal H200 off. Heavy prompts "
         "(complexity >= 0.6) skip the 30B. Unit-test rows pass their tests as `check`: a failing answer is served but not cached. "
         "Dollars are Crusoe list price ($0.29/M in, $1.20/M out). The self-hosted 30B counts as $0.", "",
         "Passes: **BASE** 763B only, no cache. **COLD** full ladder, empty Supabase namespace. **WARM** the same prompts again "
         "(every machine on the tenant sees the same rows). **GATE85** ladder with no cache and gate 0.85.", "",
         "## Per pass", "",
         "| pass | 763B calls | GPU 30B calls | cache hits | 763B tokens (in+out) | 763B $ | graded correct | p50 ms | p90 ms | errors |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for m in ORDER:
        rs = by[m]
        if not rs:
            continue
        lat = [r["latency_ms"] for r in rs]
        L.append(f"| {m} | {calls_big(m)} | {tot(m, lambda r: r['gpu_call'])} | {tot(m, hit)} | {tot(m, big)} | "
                 f"${tot(m, lambda r: r['dollars']):.5f} | {acc(rs)} | {pct(lat, .5):.0f} | {pct(lat, .9):.0f} | "
                 f"{sum(bool(r['error']) for r in rs)} |")
    bt, bd = tot("BASE", big), tot("BASE", lambda r: r["dollars"])
    if bt and by["COLD"] and by["WARM"]:
        ct, wt = tot("COLD", big), tot("WARM", big)
        cd, wd = tot("COLD", lambda r: r["dollars"]), tot("WARM", lambda r: r["dollars"])
        L += ["", "## Against the 763B-only baseline", "",
              "| | COLD | WARM | COLD + WARM vs 2 x BASE |", "|---|---|---|---|",
              f"| 763B tokens kept off | {100 * (1 - ct / bt):.1f}% | {100 * (1 - wt / bt):.1f}% | {100 * (1 - (ct + wt) / (2 * bt)):.1f}% |",
              f"| 763B $ saved | ${bd - cd:.5f} ({100 * (1 - cd / bd):.1f}%) | ${bd - wd:.5f} ({100 * (1 - wd / bd):.1f}%) | "
              f"${2 * bd - cd - wd:.5f} ({100 * (1 - (cd + wd) / (2 * bd)):.1f}%) |",
              f"| 763B calls avoided (of {n}) | {n - calls_big('COLD')} | {n - calls_big('WARM')} | "
              f"{2 * n - calls_big('COLD') - calls_big('WARM')} of {2 * n} |",
              f"| GPU and 763B calls avoided by the cache | {tot('COLD', hit)} | {tot('WARM', hit)} | {tot('COLD', hit) + tot('WARM', hit)} |"]
    if by["COLD"]:
        sh = [r["shared_ms"] for m in ("COLD", "WARM") for r in by[m] if r["shared_ms"] is not None]
        st: dict[str, int] = {}
        for m in ("COLD", "WARM"):
            for r in by[m]:
                st[str(r["shared_status"])] = st.get(str(r["shared_status"]), 0) + 1
        ex = lambda m: sum(r["tier_used"] == "exact_cache" for r in by[m])  # noqa: E731
        se = lambda m: sum(r["tier_used"] == "semantic_cache" for r in by[m])  # noqa: E731
        miss_w = [r["id"] for r in by["WARM"] if not hit(r)]
        L += ["", "## Cache (Supabase only; no machine keeps a local cache)", "",
              f"- Hit rate: COLD {tot('COLD', hit) / n:.2f} ({ex('COLD')} exact, {se('COLD')} cosine), "
              f"WARM {tot('WARM', hit) / n:.2f} ({ex('WARM')} exact, {se('WARM')} cosine). Local hit rate is 0 by design.",
              f"- WARM misses: {', '.join(miss_w) or 'none'}. These COLD answers were not cached: a failed unit test, "
              "or a 30B answer under the 0.95 cache bar.",
              f"- Lookup time (exact row and top-5 neighbours in one round trip): p50 {pct(sh, .5):.0f} ms, p90 {pct(sh, .9):.0f} ms "
              f"over {len(sh)} lookups. Statuses: {', '.join(f'{k} {v}' for k, v in sorted(st.items()))}."]
        served = [r for m in ("COLD", "WARM") for r in by[m] if hit(r) and r["grade"] is not None]
        wrong = [r["id"] for r in served if r["grade"] == 0]
        L += [f"- False hits: {len(wrong)} of {len(served)} graded cache answers were wrong"
              + (f" ({', '.join(wrong)})" if wrong else "") + "."]
    if PAIRS.exists():
        pr = json.loads(PAIRS.read_text())
        c = pr["cells"]
        L += ["", f"## Guard and threshold: {pr['n_pairs']} labeled Quora pairs ({pr['n_dup']} duplicates)", "",
              "Kaggle/GLUE QQP pairs from `bench/datasets/cache_eval.jsonl`, real MiniLM embedder, no model calls. "
              "A hit is cosine >= threshold and, with the guard on, the guard accepts.", "",
              "| threshold | guard | hits | right | wrong |", "|---|---|---|---|---|"]
        for k, v in c.items():
            t, g = k.replace("thr", "").split("_guard")
            L.append(f"| {t} | {g} | {v['hits']} | {v['right']} | {v['wrong']} |")
        L += ["", f"At 0.97 the guard cut wrong hits {c['thr0.97_guardoff']['wrong']} -> {c['thr0.97_guardon']['wrong']} and "
              f"right hits {c['thr0.97_guardoff']['right']} -> {c['thr0.97_guardon']['right']}. Default: 0.97, guard on."]
    if by["GATE85"] and by["COLD"]:
        keep = {r["id"] for r in by["COLD"] if not hit(r)}
        L += ["", "## Gate 0.85 vs 0.95 on the 30B's own answer", "",
              f"Same {len(keep)} prompts in both rows (COLD rows served from the cache are left out; GATE85 had no cache).", "",
              "| gate | answered by 30B | 30B tried, then 763B | 763B calls | 763B $ | graded correct | p50 ms |",
              "|---|---|---|---|---|---|---|"]
        for lab, m in (("0.85", "GATE85"), ("0.95", "COLD")):
            rs = [r for r in by[m] if r["id"] in keep]
            L.append(f"| {lab} | {sum(r['path'] == 'gpu-small' for r in rs)} | "
                     f"{sum(bool(r['gpu_call']) and r['path'] != 'gpu-small' for r in rs)} | {sum(1 for r in rs if big(r))} | "
                     f"${sum(r['dollars'] for r in rs):.5f} | {acc(rs)} | {pct([r['latency_ms'] for r in rs], .5):.0f} |")
    L += ["", "## Accuracy by source (graded rows)", "", "| source | BASE | COLD | WARM | GATE85 |", "|---|---|---|---|---|"]
    for src in sorted({r["src"] for r in by["COLD"]}):
        cells = [acc([r for r in by[m] if r["src"] == src]) for m in ("BASE", "COLD", "WARM", "GATE85")]
        if any(x != "n/a" for x in cells):
            L.append(f"| {src} | " + " | ".join(cells) + " |")
    L += ["", "## Latency by path (COLD, WARM, GATE85)", "", "| path | calls | p50 ms | p90 ms |", "|---|---|---|---|"]
    allr = [r for m in ORDER if m != "BASE" for r in by[m]]
    for path in sorted({r["path"] for r in allr}):
        lat = [r["latency_ms"] for r in allr if r["path"] == path]
        L.append(f"| {path} | {len(lat)} | {pct(lat, .5):.0f} | {pct(lat, .9):.0f} |")
    if verdict:
        L += ["", "## Verdict", "", verdict]
    L += ["", "## Rerun", "", "```",
          "# .env: CHIMERA_GPU_URL, CRUSOE_API_KEY, CHIMERA_DB_URL (app role); the tunnel to your GPU box is open",
          "BENCH_NS=bench-$(date +%s) .venv/bin/python bench/run_backend.py run",
          ".venv/bin/python bench/run_backend.py pairs",
          ".venv/bin/python bench/run_backend.py report", "```"]
    (ROOT / "bench/results_backend.md").write_text("\n".join(L) + "\n")
    rows = [r for m in ORDER for r in by[m]]
    with (ROOT / "bench/results_backend.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print("\n".join(L))
