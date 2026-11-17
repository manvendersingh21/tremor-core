"""The voice-over script is the docs' narration, one line per shot, within the free ElevenLabs budget (scripts/demo_voice.py)."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import demo_voice as v  # noqa: E402


def test_each_cut_has_ten_lines_in_shot_order_within_budget():
    for cut in ("live", "v2"):
        s = v.script(cut)
        assert [x["shot"] for x in s] == list(range(1, 11))
        assert [x["start"] for x in s] == sorted(x["start"] for x in s)
        assert sum(len(x["text"]) for x in s) <= 2500
    md = (ROOT / "site/docs/demo_live.md").read_text()
    assert all(f'"{x["text"]}"' in md for x in v.script("live"))   # the audio says what the doc says
