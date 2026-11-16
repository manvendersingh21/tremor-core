"""Build docs/PRD_chimera.pdf from docs/PRD_chimera.md (the source).

Handles the small markdown subset the PRD uses: #/##/### headings, paragraphs, '- ' and '1. ' lists,
pipe tables, ![caption](path) images, ``` code blocks, **bold**, `code` and [text](url).
Run scripts/prd_charts.py first so the images exist.

    .venv/bin/python scripts/prd_pdf.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (Image, KeepTogether, Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "PRD_chimera.md"
OUT = ROOT / "docs" / "PRD_chimera.pdf"
MARGIN = 0.7 * inch
FRAME_W = letter[0] - 2 * MARGIN

_ss = getSampleStyleSheet()
S = {
    "title": ParagraphStyle("t", parent=_ss["Title"], fontSize=20, leading=24, spaceAfter=6),
    "h1": ParagraphStyle("h1", parent=_ss["Heading1"], fontSize=14, leading=17, spaceBefore=12, spaceAfter=5, keepWithNext=1,
                         textColor=colors.HexColor("#1a237e")),
    "h2": ParagraphStyle("h2", parent=_ss["Heading2"], fontSize=11.5, leading=14, spaceBefore=8, spaceAfter=4,
                         keepWithNext=1),
    "body": ParagraphStyle("b", parent=_ss["BodyText"], fontSize=9.5, leading=12.5, spaceAfter=5),
    "lead": ParagraphStyle("lead", parent=_ss["BodyText"], fontSize=9.5, leading=12.5, spaceAfter=5,
                           keepWithNext=1),
    "li": ParagraphStyle("li", parent=_ss["BodyText"], fontSize=9.5, leading=12.5, leftIndent=14, spaceAfter=2),
    "cell": ParagraphStyle("c", parent=_ss["BodyText"], fontSize=7.4, leading=9),
    "cellh": ParagraphStyle("ch", parent=_ss["BodyText"], fontSize=7.4, leading=9, fontName="Helvetica-Bold"),
    "code": ParagraphStyle("code", fontName="Courier", fontSize=7.6, leading=9.4, leftIndent=6,
                           backColor=colors.HexColor("#f5f5f5"), borderPadding=4, spaceBefore=3, spaceAfter=8),
    "cap": ParagraphStyle("cap", parent=_ss["BodyText"], fontSize=8, leading=10, alignment=TA_CENTER,
                          textColor=colors.HexColor("#555555"), spaceAfter=8),
}
VERDICT = {"win": "#e8f5e9", "loss": "#ffebee", "mixed": "#fff8e1", "done": "#e8f5e9", "not done": "#ffebee",
           "partial": "#fff8e1", "measured": "#e3f2fd", "planned": "#f5f5f5", "built": "#f1f8e9"}


def inline(text: str) -> str:
    """Markdown inline -> reportlab mini-HTML. Escapes first, so file text cannot inject tags."""
    t = escape(text)
    t = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<link href="\2" color="#1565c0">\1</link>', t)
    t = re.sub(r"`([^`]+)`", r'<font face="Courier" size="-0.5">\1</font>', t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
    return t


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def table(lines: list[str]) -> Table:
    rows = [_cells(line) for line in lines if not re.fullmatch(r"\|[\s:|-]+\|", line.strip())]
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]
    weights = [min(max(len(r[i]) for r in rows), 70) + 6 for i in range(ncol)]
    widths = [FRAME_W * w / sum(weights) for w in weights]
    data = [[Paragraph(inline(c), S["cellh" if j == 0 else "cell"]) for c in r] for j, r in enumerate(rows)]
    style = [
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bdbdbd")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eceff1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]
    for r, row in enumerate(rows[1:], start=1):
        for c, cell in enumerate(row):
            low = cell.lower()
            for key, colour in VERDICT.items():
                if low == key or low.startswith(key + " ") or low.startswith(key + ":") or low.startswith(key + ","):
                    style.append(("BACKGROUND", (c, r), (c, r), colors.HexColor(colour)))
                    break
    t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle(style))
    return t


def image(caption: str, rel: str):
    path = (SRC.parent / rel).resolve()
    iw, ih = ImageReader(str(path)).getSize()
    w = min(FRAME_W, iw * 0.48)
    h = ih * w / iw
    return KeepTogether([Image(str(path), width=w, height=h), Paragraph(inline(caption), S["cap"])])


def parse(md: str) -> list:
    story: list = []
    lines = md.splitlines()
    para: list[str] = []
    i = 0

    def flush():
        if para:
            text = " ".join(para)
            # a lead-in line ("Goals:") stays on the page of the list or table it introduces
            story.append(Paragraph(inline(text), S["lead" if text.endswith(":") else "body"]))
            para.clear()

    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if s.startswith("```"):
            flush()
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith("```"):
                j += 1
            story.append(KeepTogether([Preformatted("\n".join(lines[i + 1:j]), S["code"])]))
            i = j + 1
            continue
        if s.startswith("|"):
            flush()
            j = i
            while j < len(lines) and lines[j].strip().startswith("|"):
                j += 1
            story += [table(lines[i:j]), Spacer(1, 7)]
            i = j
            continue
        m = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", s)
        if m:
            flush()
            story.append(image(m.group(1), m.group(2)))
        elif s.startswith("### "):
            flush()
            story.append(Paragraph(inline(s[4:]), S["h2"]))
        elif s.startswith("## "):
            flush()
            story.append(Paragraph(inline(s[3:]), S["h1"]))
        elif s.startswith("# "):
            flush()
            story.append(Paragraph(inline(s[2:]), S["title"]))
        elif s.startswith("- "):
            flush()
            story.append(Paragraph(inline(s[2:]), S["li"], bulletText="\u2022"))
        elif re.match(r"\d+\. ", s):
            flush()
            num, rest = s.split(". ", 1)
            story.append(Paragraph(inline(rest), S["li"], bulletText=num + "."))
        elif not s:
            flush()
        else:
            para.append(s)
        i += 1
    flush()
    return story


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#757575"))
    canvas.drawString(MARGIN, 0.45 * inch, "CHIMERA PRD and architecture, 2026-11-16. Source: docs/PRD_chimera.md")
    canvas.drawRightString(letter[0] - MARGIN, 0.45 * inch, f"page {doc.page}")
    canvas.restoreState()


def build(src: Path = SRC, out: Path = OUT) -> Path:
    doc = SimpleDocTemplate(str(out), pagesize=letter, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN,
                            bottomMargin=0.75 * inch, title="CHIMERA PRD and architecture", author="CHIMERA")
    doc.build(parse(src.read_text(encoding="utf-8")), onFirstPage=_footer, onLaterPages=_footer)
    return out


if __name__ == "__main__":
    print("wrote", build().relative_to(ROOT))
    sys.exit(0)
