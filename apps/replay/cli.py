"""bin/chimera replay <log.jsonl|csv> [--sample N] [--live | --estimate] [--volume N] [--rates file.json] [--out prefix]."""
from __future__ import annotations

import json
import pathlib
import sys

from . import estimate, logs, report


def add_parser(sub) -> None:
    p = sub.add_parser("replay", help="what would the ladder have saved on your own request log")
    p.add_argument("file", help="OpenAI-style chat log (JSONL) or CSV (columns: prompt or messages, model, prompt_tokens, completion_tokens)")
    p.add_argument("--sample", type=int, help="use a seeded random sample of N requests")
    p.add_argument("--seed", type=int, default=0)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="run the real ladder (needs the Akash tunnel, CRUSOE, GMI, Supabase keys in .env)")
    mode.add_argument("--estimate", action="store_true", help="no model calls: classify and project (default)")
    p.add_argument("--volume", type=int, help="requests per month, for the monthly table")
    p.add_argument("--rates", help="rates JSON written by a --live run; default is labelled assumptions")
    p.add_argument("--no-embed", action="store_true", help="estimate: exact repeats only, skip the cosine near-repeat check")
    p.add_argument("--judge-n", type=int, default=30, help="live: 30B answers to grade against the 763B")
    p.add_argument("--name", help="live: run name (tenant and file names); default is the file stem")
    p.add_argument("--out", help="write <out>.md and <out>.json")


def _embedder():
    from chimera_core.cache.semantic_cache import OnnxMiniLMEmbedder
    return OnnxMiniLMEmbedder().embed


def main(args) -> int:
    reqs, skipped = logs.load(args.file, args.sample, args.seed)
    if not reqs:
        print(f"error: no usable requests in {args.file} ({skipped} lines skipped)", file=sys.stderr)
        return 1
    title = f"chimera replay: {pathlib.Path(args.file).name}"
    if args.live:
        from . import live
        name = (args.name or pathlib.Path(args.file).stem).replace("_", "-")
        recs = live.run(reqs, name, args.judge_n, args.seed)
        rows, rates, quality = live.rows_and_rates(recs)
        rep = report.build(rows, "live", rates, args.volume, {"quality": quality, "skipped_lines": skipped})
        live_json = {"rates": rates, "quality": quality}
    else:
        rates = json.loads(pathlib.Path(args.rates).read_text())["rates"] if args.rates else dict(estimate.DEFAULT_RATES)
        d = estimate.DEFAULT_RATES
        rates["p30"] = {**d["p30"], **rates.get("p30", {})}  # a class the live run never saw keeps its assumed rate
        for k in ("agree", "wrong_hit", "out_tokens"):
            if rates.get(k) is None:
                rates[k] = d[k]
        classes = estimate.classify(reqs, None if args.no_embed else _embedder())
        rep = report.build(estimate.project_rows(reqs, classes, rates), "estimate", rates, args.volume, {"skipped_lines": skipped})
        live_json = None
    md = report.markdown(rep, title)
    print(md)
    if args.out:
        pathlib.Path(args.out + ".md").write_text(md)
        pathlib.Path(args.out + ".json").write_text(json.dumps(rep, indent=1, default=str))
        if live_json:
            pathlib.Path(args.out + ".rates.json").write_text(json.dumps(live_json, indent=1))
    return 0
