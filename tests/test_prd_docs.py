"""The review files exist and open: docs/PRD_chimera.pdf and docs/chimera_tracker.xlsx (offline)."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_prd_pdf_exists():
    pdf = ROOT / "docs" / "PRD_chimera.pdf"
    assert pdf.read_bytes()[:5] == b"%PDF-"
    assert (ROOT / "docs" / "PRD_chimera.md").is_file()


def test_tracker_xlsx_opens_with_live_cost_formulas():
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.load_workbook(ROOT / "docs" / "chimera_tracker.xlsx")
    assert wb.sheetnames == ["Results", "Features", "Costs", "Modal spend", "Tasks and next steps",
                             "Hackathon checklist"]
    assert str(wb["Costs"]["H2"].value).startswith("=")
    assert wb["Results"].max_row > 10
