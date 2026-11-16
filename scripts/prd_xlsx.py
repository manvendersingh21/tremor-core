"""Build docs/chimera_tracker.xlsx: results, features, costs (live formulas), tuned V100, Modal spend, tasks, hackathon.

Results, Features and the hackathon needs are read from the tables in docs/PRD_chimera.md, so the
workbook and the PRD cannot drift apart. Cost inputs are copied from the bench files named in each row.

    .venv/bin/python scripts/prd_xlsx.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "PRD_chimera.md"
OUT = ROOT / "docs" / "chimera_tracker.xlsx"

HEAD = Font(bold=True, color="FFFFFF")
HEAD_FILL = PatternFill("solid", fgColor="37474F")
INPUT_FILL = PatternFill("solid", fgColor="FFF8E1")
FILLS = {"win": "E8F5E9", "loss": "FFEBEE", "mixed": "FFF8E1", "done": "E8F5E9", "not done": "FFEBEE",
         "partial": "FFF8E1", "measured": "E3F2FD", "planned": "F5F5F5", "built": "F1F8E9"}
MONEY = '"$"#,##0.00'
MONEY4 = '"$"#,##0.0000'


def md_table(md: str, heading: str, nth: int = 0) -> list[list[str]]:
    """Rows (header first) of the nth pipe table under the '## ' heading that starts with `heading`."""
    sec = re.split(r"^## ", md, flags=re.M)
    body = next(s for s in sec if s.startswith(heading))
    tables, cur = [], []
    for line in body.splitlines():
        if line.strip().startswith("|"):
            cur.append(line)
        elif cur:
            tables.append(cur)
            cur = []
    if cur:
        tables.append(cur)
    rows = [[c.strip().replace("`", "") for c in t.strip().strip("|").split("|")] for t in tables[nth]
            if not re.fullmatch(r"\|[\s:|-]+\|", t.strip())]
    return rows


def header(ws, cols: list[str], widths: list[int], row: int = 1) -> None:
    for i, (c, w) in enumerate(zip(cols, widths), start=1):
        cell = ws.cell(row=row, column=i, value=c)
        cell.font, cell.fill = HEAD, HEAD_FILL
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def put_rows(ws, rows: list[list], start: int = 2, colour_col: int | None = None) -> None:
    for r, row in enumerate(rows, start=start):
        for c, v in enumerate(row, start=1):
            cell = ws.cell(row=r, column=c, value=v)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        if colour_col is not None:
            low = str(row[colour_col - 1]).lower()
            key = next((k for k in FILLS if low == k or re.match(re.escape(k) + r"[ :,]", low)), None)
            if key:
                ws.cell(row=r, column=colour_col).fill = PatternFill("solid", fgColor=FILLS[key])


def results(wb, md):
    ws = wb.create_sheet("Results")
    rows = md_table(md, "6. Measured results")
    header(ws, ["Test", "Setup", "Number", "Win or loss", "File"], [30, 28, 60, 16, 34])
    put_rows(ws, rows[1:], colour_col=4)


def features(wb, md):
    ws = wb.create_sheet("Features")
    rows = md_table(md, "5. Components")
    header(ws, ["Feature", "Status", "Owner file", "Proof"], [30, 22, 52, 44])
    put_rows(ws, [[r[0], r[2], r[1], r[3]] for r in rows[1:]], colour_col=2)


# (tier, $ per 1,000 coding calls, pass rate text, source)
TIERS = [
    ("Supabase cache hit (exact or cosine 0.97)", 0.0, "0 wrong in 3 repeats", "bench/results_company_cost.md"),
    ("Solved-problem bank hit", 0.0, "0 wrong served", "bench/results_company_cost.md"),
    ("30B on H200, 100% busy, 64 at once", 0.070, "270/301 = 90%", "bench/results_company_cost.md"),
    ("30B on H200, 100% busy, 32 at once", 0.096, "271/301 = 90%", "bench/results_company_cost.md"),
    ("30B on H200, one request at a time", 1.089, "270/301 = 90%", "bench/results_cost_case_h200.md"),
    ("30B on tuned V100 (Akash), 100% busy, 4 at once, $0.52/hr", 0.1775, "270/301 = 90% ($0.5223 at $1.53/hr)",
     "bench/results_akash_tuning.md"),
    ("30B on V100 (Akash) before tuning, one at a time", 11.02, "269/301 = 89%", "bench/results_cost_case.md"),
    ("763B DeepSeek-V4.1-Flash (Crusoe list)", 0.1576, "286/301 = 95%", "bench/results_cost_case.md"),
    ("Grok-4.5 (60-task subset)", 1.71, "60/60 = 100%", "bench/results_cost_case.md"),
    ("GPT-5.5 (60-task subset)", 4.02, "60/60 = 100%", "bench/results_cost_case.md"),
]


def costs(wb):
    ws = wb.create_sheet("Costs")
    vols = [100_000, 1_000_000, 10_000_000]
    header(ws, ["Tier", "$ per 1,000 calls (input)", "Pass rate", "Source",
                "$/day @100k", "$/day @1M", "$/day @10M", "$/month @100k", "$/month @1M", "$/month @10M"],
           [42, 14, 16, 32, 13, 13, 15, 14, 15, 17])
    ws["A12"] = "Calls a day (inputs used by the formulas above):"
    for j, v in enumerate(vols):
        ws.cell(row=12, column=5 + j, value=v).fill = INPUT_FILL
    for r, (name, price, pass_txt, src) in enumerate(TIERS, start=2):
        ws.cell(row=r, column=1, value=name)
        ws.cell(row=r, column=2, value=price).fill = INPUT_FILL
        ws.cell(row=r, column=3, value=pass_txt)
        ws.cell(row=r, column=4, value=src)
        for j in range(3):
            day = get_column_letter(5 + j)
            ws.cell(row=r, column=5 + j, value=f"=$B{r}*{day}$12/1000").number_format = MONEY
            ws.cell(row=r, column=8 + j, value=f"={day}{r}*30").number_format = MONEY

    # H200 price per call depends on how busy it is.
    ws["A14"] = "H200 busy share"
    ws["A14"].font = Font(bold=True)
    ws["A15"], ws["B15"] = "H200 $ per hour (Modal list)", 4.54
    ws["A16"], ws["B16"] = "H200 $ per day, always on", "=B15*24"
    ws["A17"], ws["B17"] = "H200 $ per 1,000 when 100% busy (64 at once)", 0.0700
    ws["A18"], ws["B18"] = "Busy share (try 1.0, 0.5, 0.1, 0.01)", 0.5
    ws["A19"], ws["B19"] = "H200 $ per 1,000 at that busy share", "=B17/B18"
    ws["A20"], ws["B20"] = "Break-even busy share vs 763B", "=B17/B9"
    ws["A21"], ws["B21"] = "Break-even busy share vs GPT-5.5", "=B17/B11"
    ws["D15"] = "bench/results_cost_case_h200.md, bench/results_company_cost.md"
    for c in ("B15", "B17", "B18"):
        ws[c].fill = INPUT_FILL
    for c in ("B16", "B19"):
        ws[c].number_format = MONEY4
    ws["B20"].number_format = ws["B21"].number_format = "0.0%"

    # Cascade model, same math as bench/results_company_cost.md
    ws["A23"] = "Cascade model (bench/results_company_cost.md): 30B on H200s first, failures to the API"
    ws["A23"].font = Font(bold=True)
    inputs = [
        ("Calls one H200 serves a day at 100% busy", 1_557_269),
        ("Planned load per H200 (headroom for peaks)", 0.5),
        ("30B failure share (31 of 301 fail)", "=31/301"),
        ("Supabase Pro base fee, $ a month", 25),
        ("GPT-5.5 $ per 1,000 (P_api)", 4.02),
        ("GPT-5.5 $ per 1,000 where the 30B fails (P_fail)", 6.04),
        ("763B $ per 1,000 (P_api)", 0.1576),
        ("763B $ per 1,000 where the 30B fails (P_fail)", 0.221),
    ]
    for k, (label, v) in enumerate(inputs, start=24):
        ws.cell(row=k, column=1, value=label)
        ws.cell(row=k, column=2, value=v).fill = INPUT_FILL
    # rows 24..31: B24 cap, B25 load, B26 fail, B27 db, B28 gpt api, B29 gpt fail, B30 763 api, B31 763 fail
    cols = ["Calls a day", "Share served by cache or bank (h)", "H200s", "GPT-5.5 only", "30B + GPT-5.5",
            "Saved vs GPT-5.5", "763B only", "30B + 763B", "Saved vs 763B", "File: 30B + GPT-5.5",
            "File: 30B + 763B"]
    for i, c in enumerate(cols, start=1):
        cell = ws.cell(row=33, column=i, value=c)
        cell.font, cell.fill = HEAD, HEAD_FILL
    # reference values printed in bench/results_company_cost.md, for checking the formulas
    file_vals = {(100_000, 0): (5159, 3362), (1_000_000, 0): (25216, 7246), (10_000_000, 0): (229058, 49353),
                 (100_000, 0.3): (4600, 3342), (1_000_000, 0.3): (16351, 3772), (10_000_000, 0.3): (160021, 34228)}
    r = 34
    for h in (0, 0.3):
        for d in vols:
            ws.cell(row=r, column=1, value=d).fill = INPUT_FILL
            ws.cell(row=r, column=2, value=h).fill = INPUT_FILL
            ws.cell(row=r, column=3, value=f"=ROUNDUP(A{r}*(1-B{r})/($B$24*$B$25),0)")
            gpu = f"C{r}*$B$16*30"
            fail = f"A{r}*(1-B{r})*$B$26*30"
            ws.cell(row=r, column=4, value=f"=A{r}*30*$B$28/1000")
            ws.cell(row=r, column=5, value=f"={gpu}+{fail}*$B$29/1000+$B$27")
            ws.cell(row=r, column=6, value=f"=D{r}-E{r}")
            ws.cell(row=r, column=7, value=f"=A{r}*30*$B$30/1000")
            ws.cell(row=r, column=8, value=f"={gpu}+{fail}*$B$31/1000+$B$27")
            ws.cell(row=r, column=9, value=f"=G{r}-H{r}")
            ws.cell(row=r, column=10, value=file_vals[(d, h)][0])
            ws.cell(row=r, column=11, value=file_vals[(d, h)][1])
            for c in range(4, 12):
                ws.cell(row=r, column=c).number_format = '"$"#,##0'
            ws.cell(row=r, column=2).number_format = "0%"
            r += 1
    ws.cell(row=r + 1, column=1, value="The file's inputs are rounded as printed, so the formula columns can differ "
                                         "from the 'File' columns by a few dollars. Yellow cells are inputs.")


# reference values printed in bench/results_company_cost.md (30B on tuned V100s), for checking the formulas
V100_FILE = {(100_000, 0, 0.52): (3083, 1218), (100_000, 0, 1.53): (5264, 3400),
             (1_000_000, 0, 0.52): (30227, 11585), (1_000_000, 0, 1.53): (51316, 32674),
             (10_000_000, 0, 0.52): (300174, 113757), (10_000_000, 0, 1.53): (507426, 321009),
             (100_000, 0.3, 0.52): (2128, 823), (100_000, 0.3, 1.53): (3582, 2277),
             (1_000_000, 0.3, 0.52): (21054, 8005), (1_000_000, 0.3, 1.53): (35598, 22549),
             (10_000_000, 0.3, 0.52): (210317, 79825), (10_000_000, 0.3, 1.53): (355757, 225265)}


def tuned_v100(wb):
    """Same cascade math as the Costs sheet, with the 30B on our tuned V100s (bench/results_akash_tuning.md)."""
    ws = wb.create_sheet("Tuned V100")
    ws["A1"] = ("30B on our own V100 (Akash) after tuning: num_thread 4, own Ollama, flash attention, q8 KV, 4 slots. "
                "Before tuning: $11.02 per 1,000 calls, p50 78.0 s (bench/results_cost_case.md).")
    ws["A1"].font = Font(bold=True)
    header(ws, ["Input or result", "$0.52 an hour", "$1.53 an hour", "Source"], [52, 16, 16, 40], row=2)
    rows = [
        ("Box $ per hour (always on, billed busy or idle)", 0.52, 1.53, "bench/results_akash_tuning.md", True),
        ("Box $ per day", "=B3*24", "=C3*24", "", False),
        ("Calls in the 301-task run", 301, 301, "bench/results_akash_tuning.md", True),
        ("Wall seconds of that run, 4 at once", 369.9, 369.9, "bench/results_akash_tuning.md", True),
        ("Calls a day at 100% busy", "=B5/B6*86400", "=C5/C6*86400", "", False),
        ("$ per 1,000 calls at 100% busy", "=B4/B7*1000", "=C4/C7*1000", "", False),
        ("Busy share (try 1.0, 0.5, 0.1)", 0.5, 0.5, "", True),
        ("$ per 1,000 at that busy share", "=B8/B9", "=C8/C9", "", False),
        ("Break-even busy share vs 763B (over 100% = never)", "=B8/Costs!$B$9", "=C8/Costs!$B$9", "", False),
        ("Break-even busy share vs GPT-5.5", "=B8/Costs!$B$11", "=C8/Costs!$B$11", "", False),
        ("Calls a day to beat GPT-5.5 per call", "=B12*B7", "=C12*C7", "", False),
        ("Planned load per box (headroom for peaks)", 0.5, 0.5, "bench/results_company_cost.md", True),
        ("30B failure share (31 of 301 fail)", "=31/301", "=31/301", "bench/results_akash_tuning.md", True),
        ("GPT-5.5 $ per 1,000 where this 30B fails (P_fail)", 6.26, 6.26, "bench/results_company_cost.md", True),
        ("763B $ per 1,000 where this 30B fails (P_fail)", 0.227, 0.227, "bench/results_company_cost.md", True),
        ("Supabase Pro base fee, $ a month", 25, 25, "bench/results_company_cost.md", True),
    ]
    for r, (label, b, c, src, is_input) in enumerate(rows, start=3):
        ws.cell(row=r, column=1, value=label)
        for col, v in ((2, b), (3, c)):
            cell = ws.cell(row=r, column=col, value=v)
            if is_input:
                cell.fill = INPUT_FILL
        ws.cell(row=r, column=4, value=src)
    for col in "BC":
        for k in (4, 8, 10):
            ws[f"{col}{k}"].number_format = MONEY4
        for k in (11, 12):
            ws[f"{col}{k}"].number_format = "0.0%"
        ws[f"{col}7"].number_format = ws[f"{col}13"].number_format = "#,##0"
    top = 21
    cols = ["Calls a day", "Share served by cache or bank (h)", "$ per hour column", "V100s", "GPT-5.5 only",
            "30B + GPT-5.5", "Saved vs GPT-5.5", "763B only", "30B + 763B", "Saved vs 763B", "File: 30B + GPT-5.5",
            "File: 30B + 763B"]
    for i, c in enumerate(cols, start=1):
        cell = ws.cell(row=top, column=i, value=c)
        cell.font, cell.fill = HEAD, HEAD_FILL
    r = top + 1
    for h in (0, 0.3):
        for d in (100_000, 1_000_000, 10_000_000):
            for col, price in (("B", 0.52), ("C", 1.53)):
                ws.cell(row=r, column=1, value=d).fill = INPUT_FILL
                ws.cell(row=r, column=2, value=h).fill = INPUT_FILL
                ws.cell(row=r, column=3, value=f"={col}$3").number_format = MONEY
                ws.cell(row=r, column=4, value=f"=ROUNDUP(A{r}*(1-B{r})/(${col}$7*${col}$14),0)")
                gpu = f"D{r}*${col}$4*30"
                fail = f"A{r}*(1-B{r})*${col}$15*30"
                ws.cell(row=r, column=5, value=f"=A{r}*30*Costs!$B$11/1000")
                ws.cell(row=r, column=6, value=f"={gpu}+{fail}*${col}$16/1000+${col}$18")
                ws.cell(row=r, column=7, value=f"=E{r}-F{r}")
                ws.cell(row=r, column=8, value=f"=A{r}*30*Costs!$B$9/1000")
                ws.cell(row=r, column=9, value=f"={gpu}+{fail}*${col}$17/1000+${col}$18")
                ws.cell(row=r, column=10, value=f"=H{r}-I{r}")
                ws.cell(row=r, column=11, value=V100_FILE[(d, h, price)][0])
                ws.cell(row=r, column=12, value=V100_FILE[(d, h, price)][1])
                for c in range(5, 13):
                    ws.cell(row=r, column=c).number_format = '"$"#,##0'
                ws.cell(row=r, column=2).number_format = "0%"
                r += 1
    ws.cell(row=r + 1, column=1, value="Inputs are rounded as printed, so formula columns can differ from the 'File' "
                                         "columns by a few dollars. Yellow cells are inputs. The V100 never beats the "
                                         "763B per call: even 100% busy it costs more per 1,000 calls.")


# (item, app, $, kind, source)
MODAL = [
    ("Qwen3.5-122B attempts 1-2 + H100 check (never served)", "chimera-gpu-large", 1.6, "upper bound",
     "bench/results_modal.md"),
    ("gpt-oss-120b attempt 2 (pair runs A, D)", "chimera-gpu-large", 0.87, "upper bound", "bench/results_modal.md"),
    ("Cost case on H200 30B (3 runs)", "chimera-qwen30b", 1.10, "estimate", "bench/results_cost_case_h200.md"),
    ("LoRA distill (train + 2 evals)", "chimera-distill", 8.0, "estimate", "bench/results_distill.md"),
    ("H200 30B live tier test (845 s cold start)", "chimera-qwen30b", 1.44, "upper bound",
     "bench/results_backend_v2.md"),
    ("Walk-in video clips (12 clips, Wan on H200)", "chimera-video-wan", 19.95, "estimate", "site/docs/game_clips.md"),
    ("Spec decoding, account A: weight download until its spend limit", "chimera-spec-download", 1.13, "bill",
     "bench/results_spec_modal.md"),
    ("Spec decoding, account B: downloads, smoke test, 235B job, 397B wait", "chimera-spec-*", 30.87, "bill",
     "bench/results_spec_modal.md"),
    ("Spec decoding, account C: downloads, 235B job, 480B start that hung", "chimera-spec-*", 32.57, "bill",
     "bench/results_spec_modal.md"),
]
BILL = [
    ("Billing report, 2026-11-15: chimera-video-wan", 22.59, "docs/status_2026-11-15.md"),
    ("Billing report, 2026-11-15: chimera-qwen30b", 1.20, "docs/status_2026-11-15.md"),
    ("Billing report, 2026-11-15: chimera-spec-download", 1.13, "docs/status_2026-11-15.md"),
    ("Billing report: month to date on 2026-11-15", 31.64, "docs/status_2026-11-15.md"),
    ("Spec decoding, accounts A + B + C (sum of the 3 rows above)", 64.57, "bench/results_spec_modal.md"),
]


def modal(wb):
    ws = wb.create_sheet("Modal spend")
    header(ws, ["Item", "App", "$", "Kind", "Source"], [52, 20, 10, 14, 34])
    put_rows(ws, [list(m) for m in MODAL])
    end = 1 + len(MODAL)
    ws.cell(row=end + 1, column=1, value="Sum of the per-item estimates above").font = Font(bold=True)
    ws.cell(row=end + 1, column=3, value=f"=SUM(C2:C{end})")
    ws.cell(row=end + 3, column=1, value="Bills and credits (these overlap the rows above; do not add them)").font = \
        Font(bold=True)
    for k, (item, usd, src) in enumerate(BILL, start=end + 4):
        ws.cell(row=k, column=1, value=item)
        ws.cell(row=k, column=3, value=usd)
        ws.cell(row=k, column=4, value="bill" if "Billing" in item else "total")
        ws.cell(row=k, column=5, value=src)
    last = end + 3 + len(BILL)
    ws.cell(row=last + 2, column=1, value="Account C hit its spend limit at 03:12 PST on 2026-11-16 and refuses new "
                                           "jobs; $2.01 of its $32.57 went past the credits (bench/results_spec_modal.md).")
    ws.cell(row=last + 3, column=1, value="Rates: H200 $4.54/hour, L40S $1.95/hour; volumes $0.09 per GiB-month, "
                                           "Phase A weights about 1.2 TB = about $110 a month "
                                           "(docs/status_2026-11-15.md).")
    for row in ws.iter_rows(min_row=2, max_row=last, min_col=3, max_col=3):
        row[0].number_format = MONEY


TASKS = [
    (1, "Make the H200 30B the main 30B tier, warm only under steady traffic", "backend",
     "bench/results_cost_case_h200.md", "next"),
    (2, "Test gate in front of every coding answer (bound 96.0% pass, 81.7% of 763B tokens kept off)", "backend",
     "bench/results_cost_case.md", "next"),
    (3, "Cheap pre-check: send open chat straight to the 763B", "backend", "bench/results_replay.md", "next"),
    (4, "Pitch against frontier APIs (GPT-5.5), not the 763B", "owner", "bench/results_company_cost.md", "decide"),
    (5, "Same-box spec decoding (EAGLE-3, 1.80x) for any big model we host", "backend",
     "bench/results_spec_modal.md", "later"),
    (6, "Fix non-English cache false hits (multilingual embedder or non-ASCII rule)", "backend",
     "docs/handoff/replay.md", "next"),
    (7, "Build the 30B yes/no check on cosine cache hits", "backend", ".kiro/steering/tech.md", "planned"),
    (8, "Repeat key tests 3 times on an idle GPU", "backend", "bench/results_company_cost.md", "next"),
    (9, "Public demo URL for the castle (static Pages view today; hosted demo tenant needs a spend yes)", "owner",
     "docs/hackathon/checklist.md", "decide"),
    (10, "Record the YouTube demo (under 3 minutes) from the 2:45 script", "owner", "docs/hackathon/demo_script.md",
     "script ready"),
    (11, "Kiro-use write-up and Devpost description", "frontend", "docs/hackathon/submission.md", "drafted"),
    (12, "Fix docs drift: bank is built (tech.md), no SQLite fallback (architecture.md)", "frontend",
     "docs/memory.md, docs/vector-store.md", "next"),
    (13, "Apply deploy/sql/004_eval_runs.sql so evals upload to Supabase", "backend", "docs/handoff/evals-tab.md",
     "open"),
    (14, "Make the approval token one-time (verify_approval is stateless)", "backend",
     "docs/handoff/property-tests.md", "open"),
    (15, "Finish Phase A and Phase B spec runs if credits allow", "backend", "bench/results_spec_modal.md", "blocked"),
    (16, "Stop memory hints and LoRA in their current form", "owner", "bench/results_memory.md, results_distill.md",
     "decide"),
    (17, "Delete Modal weight volumes after review (about $110 a month)", "owner", "docs/status_2026-11-15.md",
     "decide"),
    (18, "Post the blog and a social post, fill the Devpost form, tick the bonus boxes", "owner",
     "docs/hackathon/checklist.md", "hackathon"),
    (19, "Tick tasks.md in the savings-replay and lora-distill specs (built and measured, 0 ticked)", "frontend",
     ".kiro/specs/", "open"),
]


def tasks(wb):
    ws = wb.create_sheet("Tasks and next steps")
    header(ws, ["#", "Task", "Owner", "Evidence", "State"], [5, 70, 16, 40, 12])
    put_rows(ws, [list(t) for t in TASKS])


def hackathon(wb, md):
    ws = wb.create_sheet("Hackathon checklist")
    ws["A1"] = "Kiroween 2026. Deadline Fri Dec 4 2026, 2:00 PM PT. Categories: Frankenstein, Costume Contest."
    ws["A1"].font = Font(bold=True)
    needs = md_table(md, "14. Kiroween", 0)
    header(ws, ["Need", "State", "Next step", "Done?"], [30, 46, 56, 8], row=3)
    put_rows(ws, [r + ["yes" if r[1].lower().startswith("done") else "no"] for r in needs[1:]], start=4,
             colour_col=2)
    r = 4 + len(needs)
    ws.cell(row=r, column=1, value="Needs done").font = Font(bold=True)
    ws.cell(row=r, column=2, value=f'=COUNTIF(D4:D{r - 1},"yes")&" of "&COUNTA(D4:D{r - 1})')
    judging = md_table(md, "14. Kiroween", 1)
    r += 2
    for i, c in enumerate(["Judging criterion", "Our answer"], start=1):
        cell = ws.cell(row=r, column=i, value=c)
        cell.font, cell.fill = HEAD, HEAD_FILL
    put_rows(ws, judging[1:], start=r + 1)
    r += len(judging) + 1
    timeline = md_table(md, "14. Kiroween", 2)
    for i, c in enumerate(["Dates", "Work"], start=1):
        cell = ws.cell(row=r, column=i, value=c)
        cell.font, cell.fill = HEAD, HEAD_FILL
    put_rows(ws, timeline[1:], start=r + 1)


def build(out: Path = OUT) -> Path:
    md = SRC.read_text(encoding="utf-8")
    wb = Workbook()
    wb.remove(wb.active)
    results(wb, md)
    features(wb, md)
    costs(wb)
    tuned_v100(wb)
    modal(wb)
    tasks(wb)
    hackathon(wb, md)
    wb.save(out)
    return out


if __name__ == "__main__":
    print("wrote", build().relative_to(ROOT))
    sys.exit(0)
