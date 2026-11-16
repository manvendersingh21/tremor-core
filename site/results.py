"""Read the headline numbers out of bench/*.md into site/results.json.

No number is typed here: each metric names a report file and where to find the value in it
(a table row prefix + cell, or a regex). If a report changes shape the build fails loudly.
Used by site/build.py (`python3 site/build.py` writes it, `--check` compares).
"""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"


def _cell(text, prefix, idx):
    for line in text.splitlines():
        if line.startswith(prefix):
            cells = [c.strip().replace("**", "") for c in line.strip().strip("|").split("|")]
            return cells[idx]
    raise KeyError(f"row {prefix!r} not found")


def _rx(text, pattern):
    m = re.search(pattern, text)
    if not m:
        raise KeyError(f"pattern {pattern!r} not found")
    return " / ".join(g for g in m.groups() if g is not None).replace("**", "")


# (label, kind, a, b, loss). kind "c": a = row prefix, b = cell index. kind "r": a = regex, b unused.
# loss=True shows the number in red: the report itself calls it a loss or a cost.
REPORTS = [
    ("suite", "Real-dataset suite (300 questions)", "results_suite.md", [
        ("763B tokens saved by the pool", "r", r"Top-model tokens saved: ([\d.]+%)", None, False),
        ("Dollars saved at list price", "r", r"Dollars saved: ([\d.]+%)", None, False),
        ("Pass rate, 763B only / pool", "r", r"\| Pass rate \(graded items\) \| (\d+/\d+ \(\d+%\)) \| (\d+/\d+ \(\d+%\))", None, True),
        ("Median wait ms, 763B only / pool", "r", r"\| Latency median / p90 \(ms\) \| (\d+) / \d+ \| (\d+)", None, True),
    ]),
    ("cost_case", "Cost case: what each tier costs per 1,000 calls", "results_cost_case.md", [
        ("30B on the V100 before tuning, $ per 1k calls", "c", "| V100 Qwen3-30B | all |", 7, True),
        ("763B, $ per 1k calls", "c", "| DeepSeek-V4.1-Flash 763B | all |", 7, False),
        ("GPT-5.5, $ per 1k calls (60 items)", "c", "| GPT-5.5 (60 items) | all |", 7, False),
        ("Pass, 30B on V100 before tuning", "c", "| V100 Qwen3-30B | all |", 3, True),
        ("Pass, 763B", "c", "| DeepSeek-V4.1-Flash 763B | all |", 3, False),
    ]),
    ("akash_tuning", "30B on our V100 after tuning (301 coding tasks)", "results_akash_tuning.md", [
        ("Pass, tuned 30B (4 at once)", "c", "| Tuned 30B, 4 at once |", 4, False),
        ("Median s per call, tuned", "c", "| Tuned 30B, 4 at once |", 5, False),
        ("Median s per call, before tuning", "c", "| Cost case 30B ", 5, True),
        ("$ per 1k calls, tuned (box kept busy)", "c", "| Tuned 30B, 4 at once |", 7, False),
    ]),
    ("cost_case_h200", "Cost case on a Modal H200", "results_cost_case_h200.md", [
        ("30B on H200, 64 at once, $ per 1k calls", "c", "| H200, concurrency 64 |", 5, False),
        ("30B on H200, 32 at once, $ per 1k calls", "c", "| H200, concurrency 32 |", 5, False),
        ("30B on H200, one at a time, $ per 1k calls", "c", "| H200, concurrency 1 |", 5, True),
        ("An idle H200, $ per day", "r", r"idle H200 costs (\$[\d.]+) a day", None, True),
        ("Pass, 30B on H200 (64 at once)", "c", "| H200, concurrency 64 |", 6, False),
    ]),
    ("backend", "Backend end to end (60 prompts)", "results_backend.md", [
        ("763B tokens kept off, repeat run (WARM)", "c", "| 763B tokens kept off |", 2, False),
        ("763B tokens kept off, first run (COLD)", "c", "| 763B tokens kept off |", 1, False),
        ("Median ms, 763B only / cold ladder", "r", r"\| BASE \|(?:[^|]*\|){6} (\d+) \|[^\n]*\n\| COLD \|(?:[^|]*\|){6} (\d+) \|", None, True),
        ("Wrong cache answers", "r", r"False hits: (\d+ of \d+) graded cache answers were wrong", None, False),
    ]),
    ("replay", "Savings replay on real traffic (oasst1, 300)", "results_replay.md", [
        ("Answered by the 30B", "c", "| Did the 30B answer? |", 1, True),
        ("763B tokens per 1k requests", "c", "| Tokens on the 763B vs the company's model |", 1, True),
        ("Latency", "c", "| Latency |", 1, True),
        ("Dollars per 1k requests", "c", "| $ per 1k requests, ladder vs GPT-5.5-class list price |", 1, False),
    ]),
    ("bank", "Solved-problem bank (80 problems)", "results_bank.md", [
        ("Same problems again, served from the bank", "c", "| 2 same problems |", 2, False),
        ("Reworded problems, served from the bank", "c", "| 3 reworded copies |", 2, True),
        ("Reworded, answered only as a hint", "c", "| 3 reworded copies |", 3, True),
        ("Bank size", "r", r"Bank size: (\d+ pairs)", None, False),
    ]),
    ("memory", "N+1 memory (80 coding problems)", "results_memory.md", [
        ("30B alone", "c", "| 30B alone (0 stored) |", 1, False),
        ("30B + 200 stored big-model answers", "c", "| 30B + memory (200 stored) |", 1, False),
        ("Control: 3 random stored answers", "c", "| CONTROL: 30B + 3 random stored solutions (200 stored) |", 1, False),
        ("Big model alone", "c", "| Big model alone (DeepSeek-V4.1-Flash) |", 1, False),
    ]),
    ("distill", "LoRA on 763B answers (566 held-out)", "results_distill.md", [
        ("pass@1 base / tuned (%)", "r", r"fell from ([\d.]+)% to ([\d.]+)%", None, True),
        ("Solved only by base / only by tuned", "r", r"(\d+) problems only the base solved, (\d+) only the tuned", None, True),
    ]),
    ("terminal_agent", "Terminal agent `chimera code` (15 tasks)", "results_terminal_agent.md", [
        ("Tasks done fully on the 30B", "r", r"\*\*(\d+ of \d+) tasks were done fully local", None, False),
        ("Passed, ladder / 763B only", "r", r"Passed: ladder (\S+), 763B only (\S+?)\.", None, False),
        ("Dollars, ladder / 763B only", "r", r"ladder (\$[\d.]+) vs 763B only (\$[\d.]+) \((\d+% less)\)", None, False),
        ("Median seconds per task, ladder / 763B only", "r", r"median per task (\d+ s) vs ([\d.]+ s)", None, True),
    ]),
    ("spec", "Speculative decoding over the internet", "spec_results.md", [
        ("Speed against plain Ollama, K=4 and K=8", "r", r"K=4 ([\d.]+x), K=8 ([\d.]+x) \(1\.00x", None, True),
        ("Mean alpha at K=4", "c", "| alpha (mean of per-prompt) |", 1, False),
        ("Round trip floor ms (median)", "r", r"median (\d+) ms, min", None, True),
    ]),
    ("specplus", "Spec+ (stand-in target, modelled network)", "results_specplus.md", [
        ("Best Spec+ over best plain spec", "r", r"That is (1\.14x to 1\.22x) over the best plain", None, False),
        ("Big model alone, tok/s (RTT 150 ms)", "c", "| big model alone | 19.27", 1, False),
        ("Spec+ lossless, tok/s (RTT 150 ms)", "c", "| Spec+ all lossless |", 1, True),
    ]),
    ("modal", "Modal H200 120B tier (30 prompts)", "results_modal.md", [
        ("763B only: dollars", "c", "| A: 763B only |", 3, False),
        ("763B only: median ms", "c", "| A: 763B only |", 7, False),
        ("H200 120B then 763B: dollars", "c", "| D: H200 120B -> 763B |", 5, True),
        ("H200 120B then 763B: median ms", "c", "| D: H200 120B -> 763B |", 7, True),
    ]),
]


def extract():
    reports = []
    for rid, title, fname, metrics in REPORTS:
        text = (BENCH / fname).read_text(encoding="utf-8")
        out = []
        for label, kind, a, b, loss in metrics:
            if kind == "c":
                value = _cell(text, a, b).rstrip(".")
            else:
                value = _rx(text, a)
            out.append({"label": label, "value": value, "loss": loss})
        reports.append({"id": rid, "title": title, "file": f"bench/{fname}", "metrics": out})
    return reports


def headlines(reports):
    by = {r["id"]: {m["label"]: m["value"] for m in r["metrics"]} for r in reports}
    return {
        "h200_per_1k": [by["cost_case_h200"]["30B on H200, 64 at once, $ per 1k calls"],
                        by["cost_case_h200"]["30B on H200, 32 at once, $ per 1k calls"]],
        "top763_per_1k": by["cost_case"]["763B, $ per 1k calls"],
        "gpt55_per_1k": by["cost_case"]["GPT-5.5, $ per 1k calls (60 items)"],
        "v100_per_1k": by["cost_case"]["30B on the V100 before tuning, $ per 1k calls"],
        "v100_tuned_per_1k": by["akash_tuning"]["$ per 1k calls, tuned (box kept busy)"],
        "v100_tuned_p50_s": by["akash_tuning"]["Median s per call, tuned"],
        "repeat_tokens_off": by["backend"]["763B tokens kept off, repeat run (WARM)"],
        "suite_tokens_saved": by["suite"]["763B tokens saved by the pool"],
    }


def build():
    reports = extract()
    return json.dumps({"reports": reports, "headlines": headlines(reports)}, indent=1) + "\n"
