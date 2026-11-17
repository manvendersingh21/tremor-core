"""bench/daytona_gpu.py: the hourly price it logs as spend, and the .env edits it makes (offline, no Daytona call)."""
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("daytona_gpu", ROOT / "bench" / "daytona_gpu.py")
dg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dg)


def test_hourly_rate_adds_gpu_cpu_ram_and_disk_over_the_free_5_gib():
    # 1 H100 2.47 + 16 vCPU x 0.0504 + 96 GiB x 0.0162 + (300 - 5) GiB x 0.000108
    assert round(dg.rate("H100", 1, 16, 96, 300), 4) == round(2.47 + 0.8064 + 1.5552 + 0.03186, 4)
    assert dg.rate("H200", 1, 0, 0, 5) == 2.87


def test_set_env_replaces_or_removes_one_line_and_keeps_the_rest(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("A=1\nCHIMERA_120B_URL=old\nB=2\n")
    monkeypatch.setattr(dg, "ENV", env)
    dg.set_env("CHIMERA_120B_URL", "new")
    assert env.read_text().splitlines() == ["A=1", "B=2", "CHIMERA_120B_URL=new"]
    dg.set_env("CHIMERA_120B_URL", None)
    assert env.read_text().splitlines() == ["A=1", "B=2"]
    assert oct(env.stat().st_mode & 0o777) == "0o600"
