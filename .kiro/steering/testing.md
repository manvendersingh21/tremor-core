---
inclusion: always
---

# Testing

- `make test` runs `pytest -q tests` on the repo venv. It is offline: no models, no network, no keys. A test that needs a live server or key carries `@pytest.mark.live` and is skipped by default (`pyproject.toml`: `addopts = "-m 'not live'"`).
- Python 3.11 and 3.12 in CI (`.github/workflows/ci.yml`). Keep tests free of machine paths and of the contents of `.env`.
- Use fakes for the router tiers, the embedder, Supabase and Neo4j (see `tests/test_memory.py`, `tests/test_pgvector_cache.py`, `tests/test_router.py`). Never point a test at the live Supabase tables or Aura.
- Property tests use Hypothesis. Shared settings are in `tests/_props.py` (`PBT` about 200 examples, `PBT_SLOW` 50 for statistical checks). Name them `tests/test_props_*.py`. A property that fails on real code is kept and marked xfail with the shrunk counterexample. The spec that owns the properties is `.kiro/specs/chimera-speculative-os/`.
- Test layout: one `tests/test_<module>.py` per module. The save hooks in `.kiro/hooks/` run the matching file.
- New non-trivial logic (a branch, a loop, a parser, money, security) leaves one small test.
- Benchmarks are not tests. They write `bench/results*.md` and may use live tiers.
