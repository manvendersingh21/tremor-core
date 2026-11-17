"""The live demo's A6000 card reads its numbers from bench/results_a6000.md (scripts/demo_record_live.py)."""
import pathlib
import sys

import pytest

pytest.importorskip("playwright")
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import demo_record_live as d  # noqa: E402


def test_card_numbers_come_from_the_results_file():
    a = d.a6000()
    text = (ROOT / d.A6).read_text()
    assert f"cut {a['cut']}% of big-model calls with 0 wrong answers from the cache" in text
    assert f"Cost case: correct of {a['n']} | {a['base_ok']} |" in text and f"**{a['ladder_ok']}**" in text
    html, _ = d.card_js()
    assert f"{a['cut']}% fewer 763B calls" in html and "A loss" in html
