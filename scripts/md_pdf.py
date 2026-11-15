"""Markdown -> PDF, offline: markdown-it-py renders HTML, headless Chrome prints it.

  .venv/bin/python scripts/md_pdf.py docs/status_2026-11-15.md        # writes docs/status_2026-11-15.pdf

Uses the same Chrome as scripts/cdp.py (the Playwright headless shell if cached). Raw HTML in the Markdown (inline
SVG diagrams) is kept. The HTML is written next to the PDF in bench/.scratch/ui/ (git-ignored) for checking.
"""
import pathlib
import subprocess
import sys
import tempfile

from markdown_it import MarkdownIt

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from cdp import CHROME  # noqa: E402

CSS = """
@page { size: A4; margin: 16mm 14mm 16mm 14mm; }
body { font: 10.5pt/1.45 -apple-system, "Helvetica Neue", Arial, sans-serif; color: #1d1d1f; }
h1 { font-size: 20pt; margin: 0 0 4pt; } h2 { font-size: 14pt; margin: 16pt 0 6pt; border-bottom: 1px solid #ccc; }
h3 { font-size: 11.5pt; margin: 12pt 0 4pt; } p, li { margin: 3pt 0; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0; font-size: 8.8pt; page-break-inside: auto; }
tr { page-break-inside: avoid; } th, td { border: 1px solid #c8c8c8; padding: 3pt 5pt; vertical-align: top; text-align: left; }
th { background: #f0f0f2; } code { font: 8.8pt Menlo, monospace; background: #f4f4f6; padding: 0 2pt; }
pre { background: #f4f4f6; padding: 6pt; font-size: 8pt; overflow: hidden; page-break-inside: avoid; }
pre code { background: none; padding: 0; } svg { max-width: 100%; height: auto; }
.win { color: #0a7a2f; font-weight: 600; } .loss { color: #b3261e; font-weight: 600; } .mixed { color: #8a5a00; font-weight: 600; }
"""


def render(md_path: pathlib.Path) -> str:
    md = MarkdownIt("commonmark", {"html": True}).enable("table")
    body = md.render(md_path.read_text())
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{body}</body></html>"


def to_pdf(md_path: pathlib.Path, pdf_path: pathlib.Path | None = None) -> pathlib.Path:
    pdf_path = pdf_path or md_path.with_suffix(".pdf")
    scratch = ROOT / "bench" / ".scratch" / "ui"
    scratch.mkdir(parents=True, exist_ok=True)
    html = scratch / (md_path.stem + ".html")
    html.write_text(render(md_path))
    with tempfile.TemporaryDirectory(dir=scratch) as prof:
        args = [CHROME, *([] if "headless-shell" in CHROME else ["--headless=new"]), "--no-sandbox", "--disable-gpu",
                f"--user-data-dir={prof}", "--no-pdf-header-footer", "--virtual-time-budget=5000",
                f"--print-to-pdf={pdf_path}", html.as_uri()]
        subprocess.run(args, check=True, capture_output=True, timeout=120)
    if not pdf_path.exists() or pdf_path.stat().st_size < 1000:
        raise RuntimeError(f"no PDF written: {pdf_path}")
    return pdf_path


if __name__ == "__main__":
    print(to_pdf(pathlib.Path(sys.argv[1]).resolve()))
