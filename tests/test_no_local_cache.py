"""The answer cache lives only in Supabase: the production path never creates or writes a local cache file."""
import pathlib

from chimera_core.config import ChimeraConfig, build_router
from chimera_core.tiers import TierCfg

from test_events import Bag, Fake


def _files(root: pathlib.Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


def test_default_config_has_no_local_cache_and_writes_no_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))  # ~/.chimera/cache.db would land here
    monkeypatch.setenv("CHIMERA_DB_URL", "postgresql://u:p@127.0.0.1:1/none")  # refused at once: DB down
    cfg = ChimeraConfig(use_pool=True, memory={"enabled": False}, telemetry={"path": str(tmp_path / "logs" / "t.jsonl")},
                        tiers=[TierCfg(name="mac", device="laptop", backend="llamacpp", url="http://x", model="m")])
    assert cfg.cache.backend == "supabase" and cfg.cache.guard and cfg.thresholds.confidence == 0.95
    r = build_router(cfg, embedder=Bag())
    assert r.exact is None and r.semantic is None and r.shared is not None and r.shared.fallback is None
    r.pool._factory = lambda t: Fake("mac", conf=0.99)
    r.pool._probe = lambda t: True
    got = []
    for _ in range(2):
        res = r.generate("what is the capital of France", on_event=lambda s, d: got.append((s, d)))
    r.shared._wpool.shutdown(wait=True)  # let the (failing) background write finish
    shared = [d for s, d in got if s == "cache_shared"]
    assert [d["status"] for d in shared] == ["unavailable", "unavailable"] and "cache_local" not in [s for s, _ in got]
    assert res.telemetry.tier_used == "local"  # second call was not served from any local cache
    assert _files(tmp_path) == {"logs/t.jsonl"}  # telemetry log only; no cache.db, no sqlite file anywhere


def test_no_dsn_means_no_cache_at_all(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CHIMERA_DB_URL", raising=False)
    monkeypatch.setattr("chimera_core.config.load_env", lambda *a, **k: None)
    cfg = ChimeraConfig(use_pool=True, memory={"enabled": False}, telemetry={"path": str(tmp_path / "t.jsonl")},
                        tiers=[TierCfg(name="mac", device="laptop", backend="llamacpp", url="http://x", model="m")])
    r = build_router(cfg, embedder=Bag())
    assert (r.exact, r.semantic, r.shared) == (None, None, None)
    assert not (tmp_path / ".chimera").exists()


def test_memory_that_cannot_start_is_turned_off(monkeypatch):
    import chimera_core.memory as mem
    from chimera_core.config import make_memory

    def boom(*a, **k):
        raise ModuleNotFoundError("neo4j")

    monkeypatch.setattr(mem, "build", boom)
    assert make_memory(ChimeraConfig(), Bag()) is None
    assert make_memory(ChimeraConfig(memory={"enabled": False}), Bag()) is None
