"""skeleton/apps/coder: offline demo (stub tiers), path safety, the diff."""
import pytest

from skeleton.apps.coder.coder import Coder, main
from skeleton.apps.coder.demo import DEMO_MODELS, run


def test_demo_climbs_on_failed_tests_then_serves_from_cache():
    rows = run()
    first = {r["task"]: r for r in rows if r["pass"] == 1}
    assert first["fix-add"]["tried"] == ["gpu-small", "cloud-deepseek"] and first["fix-add"]["climbs"] == 1
    assert first["greet"]["tier"] == "gpu-small" and first["clamp"]["tier"] == "gpu-small"
    second = [r for r in rows if r["pass"] == 2]
    assert all(r["cache_hit"] and r["tokens"] == 0 and r["verified"] for r in second)
    assert all(r["verified"] for r in rows)


def test_patch_shows_a_diff_and_apply_writes_only_after_tests(tmp_path):
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    (tmp_path / "check.py").write_text("from calc import add\nassert add(2, 3) == 5\n")
    import sys
    c = Coder(tmp_path, ["calc.py"], f"{sys.executable} check.py", demo_models=DEMO_MODELS)
    r = c.ask("Fix add() in calc.py so that add(2, 3) == 5.")
    assert r.answer["verified"] and "+    return a + b" in r.diff
    assert "a - b" in (tmp_path / "calc.py").read_text()  # not applied yet
    c.apply(r.changes)
    assert "a + b" in (tmp_path / "calc.py").read_text()


def test_refuses_paths_outside_the_repo_and_secret_files(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    with pytest.raises(ValueError):
        Coder(tmp_path, ["../a.py"], "true")
    c = Coder(tmp_path, ["a.py"], "true")
    for bad in ("../evil.py", ".env", "keys/id_rsa", ".git/config"):
        changes, errors = c.changes(f"FILE: {bad}\nboom\nEND FILE")
        assert changes == {} and errors, bad


def test_cli_demo_exits_zero(capsys):
    assert main(["demo"]) == 0
    assert "climb" in capsys.readouterr().out
