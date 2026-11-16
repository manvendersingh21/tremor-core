"""Charts and block diagrams for docs/PRD_chimera.md (and the PDF built from it).

Every number below is copied from the results file named next to it. No model,
network or database call is made. Output: docs/prd/*.png.

    .venv/bin/python scripts/prd_charts.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "prd"

WIN, LOSS, MIX, GREY, BLUE = "#2e7d32", "#c62828", "#ef8f00", "#757575", "#1565c0"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.spines.top": False,
                     "axes.spines.right": False, "figure.dpi": 150})


def _save(fig, name: str, source: str) -> Path:
    fig.text(0.01, -0.03, "Source: " + source, fontsize=7, color=GREY, ha="left", va="top")
    path = OUT / name
    fig.savefig(path, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    return path


# ---------------------------------------------------------------- charts

def cost_per_1k() -> Path:
    # (label, $ per 1,000 calls, colour); results_company_cost.md table "Cost per 1,000 coding calls"
    rows = [
        ("Supabase cache hit", 0.0, WIN),
        ("Solved-problem bank hit", 0.0, WIN),
        ("30B on H200, 100% busy (64 at once)", 0.070, WIN),
        ("30B on H200, 100% busy (32 at once)", 0.096, WIN),
        ("763B DeepSeek-V4.1-Flash (Crusoe)", 0.1576, BLUE),
        ("30B on tuned V100, 100% busy ($0.52/hr)", 0.178, WIN),  # results_akash_tuning.md
        ("30B on tuned V100, 100% busy ($1.53/hr)", 0.522, MIX),
        ("30B on H200, 10% busy", 0.700, MIX),
        ("30B on H200, one request at a time", 1.089, MIX),
        ("Grok-4.5 (60-task subset)", 1.71, GREY),
        ("GPT-5.5 (60-task subset)", 4.02, GREY),
        ("30B on H200, 1% busy", 6.997, LOSS),
        ("30B on V100 before tuning (Akash)", 11.02, LOSS),
    ]
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    labels = [r[0] for r in rows]
    vals = [max(r[1], 0.01) for r in rows]
    ax.barh(labels, vals, color=[r[2] for r in rows])
    ax.set_xscale("log")
    ax.invert_yaxis()
    ax.set_xlabel("$ per 1,000 coding calls (log scale; $0 drawn at $0.01)")
    for i, r in enumerate(rows):
        ax.text(vals[i] * 1.15, i, "$0" if r[1] == 0 else (f"${r[1]:.3f}" if r[1] < 1 else f"${r[1]:.2f}"),
                va="center", fontsize=8)
    ax.set_xlim(0.008, 40)
    ax.set_title("Cost per 1,000 coding calls by tier")
    return _save(fig, "cost_per_1k.png",
                 "bench/results_company_cost.md, results_cost_case.md, results_cost_case_h200.md, results_akash_tuning.md")


def tokens_saved() -> Path:
    # (label, % of big-model tokens kept off, file)
    rows = [
        ("Backend v1 WARM (repeats)", 97.5, "results_backend.md"),
        ("Ladder L4 vs 763B only", 65.6, "results_ladder.md"),
        ("Backend v2 COLD (new prompts)", 53.0, "results_backend_v2.md"),
        ("Ladder L vs gpt-oss-120b only", 45.1, "results_ladder.md"),
        ("Real-dataset suite, 300 items", 38.4, "results_suite.md"),
        ("Backend v1 COLD (new prompts)", 12.2, "results_backend.md"),
        ("oasst1 chat replay, 300 requests", -9.8, "results_replay.md"),
        ("Mac cascade vs GPU only (GPU tokens)", -37.1, "results_gpu.md"),
    ]
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    vals = [r[1] for r in rows]
    ax.barh([r[0] for r in rows], vals, color=[WIN if v > 0 else LOSS for v in vals])
    ax.axvline(0, color="#333", lw=0.8)
    ax.invert_yaxis()
    for i, v in enumerate(vals):
        ax.text(v + (2 if v >= 0 else -2), i, f"{v:+.1f}%", va="center", ha="left" if v >= 0 else "right",
                fontsize=8)
    ax.set_xlim(-60, 115)
    ax.set_xlabel("Big-model tokens kept off (%). Negative = the cascade sent more.")
    ax.set_title("Tokens saved on the big model, per test (single runs)")
    return _save(fig, "tokens_saved.png", "bench/" + ", ".join(sorted({r[2] for r in rows})))


def accuracy_by_tier() -> Path:
    # pass % by difficulty on the cost-case tasks
    tiers = [
        ("30B on V100", [98, 90, 78, 89], "results_cost_case.md"),
        ("30B on H200", [98, 89, 80, 90], "results_cost_case_h200.md"),
        ("763B", [100, 92, 92, 95], "results_cost_case.md"),
        ("GPT-5.5 (60 tasks)", [100, 100, 100, 100], "results_cost_case.md"),
    ]
    groups = ["trivial (101)", "everyday (120)", "hard (80)", "all (301)"]
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    w = 0.2
    colors = [MIX, WIN, BLUE, GREY]
    for i, (name, vals, _) in enumerate(tiers):
        xs = [g + (i - 1.5) * w for g in range(len(groups))]
        ax.bar(xs, vals, w, label=name, color=colors[i])
        for x, v in zip(xs, vals):
            ax.text(x, v + 0.6, str(v), ha="center", fontsize=7)
    ax.set_xticks(range(len(groups)), groups)
    ax.set_ylim(60, 110)
    ax.set_ylabel("Pass rate (%), code run against tests")
    ax.legend(ncol=4, fontsize=7, loc="upper center", frameon=False)
    ax.set_title("Accuracy by tier on the 301 coding tasks")
    return _save(fig, "accuracy_by_tier.png",
                 "bench/results_cost_case.md, results_cost_case_h200.md (GPT-5.5 on a 60-task subset)")


def spec_speed() -> Path:
    # Phase A, Qwen3-235B-A22B verifier, accounts B and C (results_spec_modal.md) and Mac->V100 (spec_results.md)
    a = [
        ("235B alone (B)", 89.8, BLUE),
        ("235B alone (C)", 86.2, BLUE),
        ("30B drafter alone (B)", 129.7, GREY),
        ("2 boxes: 30B, K=4 (B)", 20.5, LOSS),
        ("2 boxes: 30B, K=8 (B)", 22.7, LOSS),
        ("2 boxes: 30B, Spec+ (B)", 24.4, LOSS),
        ("2 boxes: K=4 +100 ms (B)", 14.0, LOSS),
        ("2 boxes: 4B, K=4 (C)", 13.2, LOSS),
        ("2 boxes: 4B->30B chain (C)", 7.3, LOSS),
        ("same box: 4B draft (C)", 27.3, LOSS),
        ("same box: n-gram (B)", 100.6, WIN),
        ("same box: EAGLE-3 (B)", 162.2, WIN),
    ]
    b = [("Plain Ollama 30B", 14.60, BLUE), ("Mac 3B -> V100, K=4", 2.14, LOSS),
         ("Mac 3B -> V100, K=8", 3.27, LOSS)]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.4, 4.2), gridspec_kw={"width_ratios": [2.2, 1]})
    ax1.barh([r[0] for r in a], [r[1] for r in a], color=[r[2] for r in a])
    ax1.invert_yaxis()
    for i, r in enumerate(a):
        ax1.text(r[1] + 2, i, f"{r[1]:.1f}", va="center", fontsize=7)
    ax1.set_xlim(0, 185)
    ax1.set_xlabel("tokens / s (48 prompts)")
    ax1.set_title("Modal: 235B verifier", fontsize=9)
    ax2.barh([r[0] for r in b], [r[1] for r in b], color=[r[2] for r in b])
    ax2.invert_yaxis()
    for i, r in enumerate(b):
        ax2.text(r[1] + 0.3, i, f"{r[1]:.2f}", va="center", fontsize=7)
    ax2.set_xlim(0, 18)
    ax2.set_xlabel("tokens / s (10 prompts)")
    ax2.set_title("Mac -> V100 over the internet", fontsize=9)
    fig.suptitle("Speculative decoding: same box wins, two boxes lose", fontsize=10)
    fig.tight_layout()
    return _save(fig, "spec_speed.png", "bench/results_spec_modal.md (accounts B and C), bench/spec_results.md")


def hit_rates() -> Path:
    rows = [
        ("Backend v2 WARM: 60 repeats", 100.0, "60/60"),
        ("Backend v1 WARM: 60 repeats", 95.0, "57/60"),
        ("Bank run 2: same 80 problems", 93.8, "75/80"),
        ("Cache, 2nd client (x3 repeats)", 81.7, "49/60"),
        ("Bank run 3: 80 reworded", 30.0, "24/80"),
        ("Suite: real Quora duplicates", 8.3, "2/24"),
        ("Quora replay: 1,000 questions", 2.4, "24/1000 (max 181)"),
        ("oasst1 replay: 300 chats", 0.7, "2/300"),
    ]
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    vals = [r[1] for r in rows]
    ax.barh([r[0] for r in rows], vals, color=[WIN if v >= 50 else (MIX if v >= 10 else LOSS) for v in vals])
    ax.invert_yaxis()
    for i, r in enumerate(rows):
        ax.text(r[1] + 1, i, f"{r[1]:.1f}%  ({r[2]})", va="center", fontsize=7)
    ax.set_xlim(0, 135)
    ax.set_xlabel("Served from cache or bank (%)")
    ax.set_title("Hit rates: high on repeats, low on real traffic")
    return _save(fig, "hit_rates.png",
                 "bench/results_backend.md, results_backend_v2.md, results_bank.md, results_company_cost.md, "
                 "results_suite.md, results_replay.md")


def monthly_cost() -> Path:
    # results_company_cost.md, h = 0 (no repeats)
    vols = ["100k / day", "1M / day", "10M / day"]
    series = [
        ("GPT-5.5 only", [12060, 120600, 1206000], GREY),
        ("30B on H200s + GPT-5.5 for failures", [5159, 25216, 229058], WIN),
        ("30B on tuned V100s ($0.52/hr) + GPT-5.5", [3083, 30227, 300174], MIX),
        ("763B only", [473, 4728, 47280], BLUE),
        ("30B on H200s + 763B for failures", [3362, 7246, 49353], LOSS),
    ]
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    w = 0.16
    for i, (name, vals, c) in enumerate(series):
        xs = [g + (i - 2) * w for g in range(3)]
        ax.bar(xs, vals, w, label=name, color=c)
        for x, v in zip(xs, vals):
            ax.text(x, v * 1.15, f"${v:,.0f}", ha="center", fontsize=6, rotation=90, va="bottom")
    ax.set_yscale("log")
    ax.set_ylim(100, 8e7)
    ax.set_xticks(range(3), vols)
    ax.set_ylabel("$ per month (log scale)")
    ax.legend(ncol=2, fontsize=7, frameon=False, loc="upper left")
    ax.set_title("Monthly cost, coding calls, no repeats (h = 0)")
    return _save(fig, "monthly_cost.png", "bench/results_company_cost.md")


# ---------------------------------------------------------------- diagrams

def _box(ax, x, y, w, h, text, fc="#ffffff", ec="#444", dashed=False, bold_first=True, fs=7.5):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08", fc=fc, ec=ec,
                                lw=1.1, ls="--" if dashed else "-"))
    lines = text.split("\n")
    n = len(lines)
    for i, line in enumerate(lines):
        ax.text(x + w / 2, y + h - (i + 1) * h / (n + 1), line, ha="center", va="center", fontsize=fs,
                weight="bold" if (bold_first and i == 0) else "normal")


def _arrow(ax, a, b, text="", color="#444", dashed=False, fs=6.5, off=(0, 0.08)):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=9, color=color, lw=1.0,
                                 ls="--" if dashed else "-"))
    if text:
        ax.text((a[0] + b[0]) / 2 + off[0], (a[1] + b[1]) / 2 + off[1], text, ha="center", fontsize=fs,
                color="#333")


def _canvas(w, h):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(0, w)
    ax.set_ylim(0, h)
    ax.axis("off")
    return fig, ax


def ladder_flow() -> Path:
    fig, ax = _canvas(11.6, 4.6)
    bw = 1.6
    _box(ax, 0.1, 2.9, 1.1, 0.9, "Prompt\nfrom a surface", "#f4f4f4", fs=7)
    tiers = [
        (1.6, "0. Supabase cache\nexact hash, then\ncosine >= 0.97 + guard", "#e3f2fd", False),
        (3.65, "1. Solved bank\nserve only if its\ntests pass now", "#e3f2fd", False),
        (5.7, "2. 30B\nH200 if warm, else V100\n+ N+1 memory hints", "#e8f5e9", False),
        (7.75, "3. Modal 120B\ngpt-oss-120b\noff by default", "#f4f4f4", True),
        (9.8, "4. Crusoe 763B\nDeepSeek-V4.1-Flash\nthe top", "#fff3e0", False),
    ]
    for x, t, fc, d in tiers:
        _box(ax, x, 2.75, bw, 1.2, t, fc, dashed=d, fs=7)
    _arrow(ax, (1.2, 3.35), (1.6, 3.35))
    for i in range(4):
        x0 = tiers[i][0] + bw
        _arrow(ax, (x0, 3.35), (tiers[i + 1][0], 3.35), "miss" if i < 2 else "climb", off=(0, 0.14), fs=6)
    _box(ax, 1.6, 0.35, 9.95, 0.75, "Answer to the caller\ntier, tokens, ms and $ logged for every call (inference/telemetry.py)",
         "#fafafa")
    labels = ["hit ~120 ms, $0", "served, $0", "gate p >= 0.95", "if on", "always"]
    for (x, *_), lab in zip(tiers, labels):
        _arrow(ax, (x + bw / 2, 2.75), (x + bw / 2, 1.1), lab, off=(0.45, 0))
    ax.text(9.2, 4.3, "763B answers that pass their tests -> teacher_pairs (Supabase)\n"
            "+ Neo4j Aura graph + bank + cache", ha="center", fontsize=6.5, color="#555")
    _arrow(ax, (9.8, 4.15), (6.6, 4.15), dashed=True, color="#777")
    ax.text(0.1, 4.45, "Heavy prompts (complexity >= 0.6) skip the 30B. A failed check climbs one tier.",
            fontsize=7, color="#333")
    return _save(fig, "ladder_flow.png", "docs/architecture.md, docs/memory.md, bench/results_backend_v2.md")


def system_blocks() -> Path:
    fig, ax = _canvas(9.6, 4.4)
    surfaces = ["Web castle\n127.0.0.1:8765", "chimera code\nterminal coder", "Gateway\nOpenAI-style",
                "Kiro MCP, CLI,\nhook", "Android tier\nnot tested"]
    for i, s in enumerate(surfaces):
        _box(ax, 0.1 + i * 1.9, 3.35, 1.7, 0.8, s, "#f3e5f5", dashed=(i == 4))
        _arrow(ax, (0.95 + i * 1.9, 3.35), (4.8, 2.75), color="#999")
    _box(ax, 2.6, 1.95, 4.4, 0.8,
         "Router: SpeculativeCascadeRouter.generate()\nrouter.py + tiers.py pool + service.py (/api/chat, /api/stats)",
         "#e3f2fd")
    _box(ax, 0.1, 0.25, 2.3, 1.2, "Supabase (Postgres)\nprompts cache, solved_bank,\nteacher_pairs, mem_*", "#e8f5e9")
    _box(ax, 2.6, 0.25, 1.9, 1.2, "Neo4j Aura\nconcept graph\n(memory/neo4j_store.py)", "#e8f5e9")
    _box(ax, 4.7, 0.25, 2.3, 1.2, "GPU 30B\nModal H200 (warm only)\nAkash V100 (tunnel)", "#fffde7")
    _box(ax, 7.2, 0.25, 2.3, 1.2, "Clouds\nCrusoe 763B (top)\nModal 120B (off)", "#fff3e0")
    _box(ax, 7.3, 1.95, 2.2, 0.8, "Safety\nscrub(), risk score,\nsecret-scan hooks", "#ffebee")
    for x in (1.25, 3.55, 5.85, 8.35):
        _arrow(ax, (4.8, 1.95), (x, 1.45), color="#555")
    _arrow(ax, (7.0, 2.35), (7.3, 2.35), color="#c62828")
    return _save(fig, "system_blocks.png", "docs/architecture.md, .kiro/steering/structure.md")


def spec_boxes() -> Path:
    fig, ax = _canvas(9.6, 3.4)
    ax.text(2.3, 3.15, "Two boxes (measured: 0.15x to 0.27x)", ha="center", weight="bold", color=LOSS)
    _box(ax, 0.2, 1.6, 1.6, 1.0, "Drafter box\nsmall model\nwrites K tokens", "#e8f5e9")
    _box(ax, 2.9, 1.6, 1.6, 1.0, "Verifier box\nbig model\nchecks K in 1 pass", "#fff3e0")
    _arrow(ax, (1.8, 2.35), (2.9, 2.35), "K token ids", off=(0, 0.1))
    _arrow(ax, (2.9, 1.85), (1.8, 1.85), "accepted m + 1 token", off=(0, -0.42))
    ax.text(2.35, 0.95, "One network round trip per round\n(58 ms median on Modal, ~600 ms Mac -> V100)",
            ha="center", fontsize=7)
    ax.text(7.3, 3.15, "Same box on the 235B (n-gram 1.12x, EAGLE-3 1.80x)", ha="center", weight="bold",
            color=WIN)
    _box(ax, 5.6, 1.4, 3.4, 1.4, "One vLLM server\nbig model + EAGLE-3 head\nor n-gram prompt lookup\nno network between draft and check",
         "#e3f2fd")
    ax.text(4.8, 0.35, "Output equals the big model alone (greedy). Only [token_id, logprob] would cross the wire; KV caches stay put.",
            ha="center", fontsize=7, color="#444")
    return _save(fig, "spec_boxes.png", "bench/results_spec_modal.md, bench/spec_results.md, docs/architecture.md")


def memory_graph() -> Path:
    # Node counts from bench/results_memory.md "Stores" (tenant bench-n1): problem 200, solution 200,
    # concept 368, pattern 200, error 0, edges 1138 (total; the file has no count per edge type).
    fig, ax = _canvas(9.6, 4.2)
    nodes = {
        "Problem": (0.4, 2.3, "Problem\n200 nodes", "#e3f2fd"),
        "Solution": (3.7, 2.3, "Solution\n200 nodes", "#e8f5e9"),
        "Concept": (7.2, 2.3, "Concept (idea)\n368 nodes", "#fff3e0"),
        "Pattern": (3.7, 0.3, "Pattern\n'why it works'\n200 nodes", "#f3e5f5"),
        "Error": (7.2, 0.3, "Error\n0 nodes", "#ffebee"),
        "Problem2": (0.4, 0.3, "Problem\n(another one)", "#e3f2fd"),
    }
    for _, (x, y, t, fc) in nodes.items():
        _box(ax, x, y, 2.0, 1.0, t, fc, dashed=t.startswith("Error") or "another" in t)
    _arrow(ax, (2.4, 2.8), (3.7, 2.8), "SOLVED_BY")
    _arrow(ax, (5.7, 2.8), (7.2, 2.8), "USES")
    _arrow(ax, (4.7, 1.3), (4.7, 2.3), "PART_OF", off=(0.4, 0))
    _arrow(ax, (5.7, 2.45), (7.6, 1.3), "FIXES (fixed error)", off=(0.6, 0.05))
    _arrow(ax, (1.4, 2.3), (1.4, 1.3), "SIMILAR_TO {score}", off=(0.65, 0))
    ax.text(4.8, 3.75, "Neo4j Aura graph, tenant bench-n1: 968 nodes, 1,138 edges in total "
            "(teacher_pairs rows: 200)", ha="center", fontsize=8, weight="bold")
    ax.text(4.8, 3.5, "Every node also has label :Mem and id, tenant, text, 384-d embedding, created_at. "
            "Edge counts per type were not recorded.", ha="center", fontsize=6.5, color="#555")
    return _save(fig, "memory_graph.png", "bench/results_memory.md (Stores), docs/memory.md (graph model)")


ALL = [cost_per_1k, tokens_saved, accuracy_by_tier, spec_speed, hit_rates, monthly_cost,
       ladder_flow, system_blocks, spec_boxes, memory_graph]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for fn in ALL:
        print("wrote", fn().relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
