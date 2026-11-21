"""coder CLI: every tier failing ends in a clear message, not a traceback."""
from skeleton.apps.coder.coder import Coder, main


def test_cli_reports_all_tiers_failed_without_a_traceback(tmp_path, capsys, monkeypatch):
    from chimera_core.tiers import AllTiersFailed
    (tmp_path / "a.py").write_text("x = 1\n")

    def boom(self, task):
        raise AllTiersFailed("no tier answered (tried: ['cloud-deepseek'])")
    monkeypatch.setattr(Coder, "ask", boom)
    rc = main(["ask", "do it", "--repo", str(tmp_path), "--file", "a.py", "--test", "true"])
    assert rc == 2 and "no tier answered" in capsys.readouterr().err
