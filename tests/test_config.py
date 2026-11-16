"""config.tier_checks: with the tier pool on, `chimera doctor` probes the enabled pool tiers, not the unused [local]/[gpu]."""
from chimera_core.config import ChimeraConfig, tier_checks


def test_tier_checks_follow_the_pool(monkeypatch):
    monkeypatch.setenv("T_GPU_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("T_KEY", "k")
    cfg = ChimeraConfig(use_pool=True, tiers=[
        {"name": "gpu-small", "device": "gpu", "backend": "ollama", "url": "$T_GPU_URL"},
        {"name": "off", "device": "laptop", "backend": "llamacpp", "url": "http://127.0.0.1:8", "enabled": False},
        {"name": "top", "device": "cloud", "backend": "openai", "url": "https://example.invalid", "api_key_env": "T_KEY"},
    ])
    checks = tier_checks(cfg)
    assert [c[0] for c in checks] == ["gpu-small", "top"]
    assert checks[0][2] == "http://127.0.0.1:9/api/tags" and checks[0][3] == {}
    assert checks[1][2] == "https://example.invalid/v1/models" and checks[1][3] == {"Authorization": "Bearer k"}


def test_tier_checks_without_pool_keep_fixed_ladder():
    assert [c[0] for c in tier_checks(ChimeraConfig())][:1] == ["local"]


def test_shared_cache_link_is_opened_at_build(monkeypatch):
    # Found live (bench/results_backend_v3.md): the first lookup of each process ran past its 300 ms budget.
    import threading

    from chimera_core.cache import pgvector_cache as pg
    from chimera_core.config import make_caches
    pinged = threading.Event()
    monkeypatch.setattr(pg.PgVectorCache, "ping", lambda self, timeout_s=3.0: pinged.set() or 1.0)
    monkeypatch.setenv("CHIMERA_DB_URL", "postgresql://u@127.0.0.1:1/x")
    shared = make_caches(ChimeraConfig(), embedder=object(), threshold=0.97)[2]
    assert shared is not None and pinged.wait(5)
