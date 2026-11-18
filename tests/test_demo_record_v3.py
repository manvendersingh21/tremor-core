"""Demo v3 narration: 10 lines, every number in words, within the voice budget, and shot 10 says what
bench/results_a6000.md says (scripts/demo_record_v3.py)."""
import pathlib
import sys

import pytest

pytest.importorskip("playwright")
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import demo_record_v3 as d  # noqa: E402


def test_narration_has_no_digits_and_fits_the_budget():
    say = d.narration()
    assert sorted(say) == list(range(1, 11))
    assert not any(c.isdigit() or c in "%$" for t in say.values() for c in t)
    assert sum(map(len, say.values())) <= d.MAX_CHARS
    assert "seventy point seven percent" in say[10] and "two hundred ninety-two of three hundred one" in say[10]


def test_shot_10_numbers_match_the_results_file():
    _, a = d.card_js()
    assert {k: a[k] for k in d.SAID} == d.SAID
