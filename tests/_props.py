"""Shared Hypothesis settings for tests/test_props_*.py (PBT tasks in .kiro/specs/chimera-speculative-os/tasks.md).

About 200 examples and a per-example deadline keep `make test` and CI quick. Shrunk counterexamples are printed by
Hypothesis; a property that fails on real code is kept and marked xfail with the counterexample (docs/handoff/property-tests.md).
"""
from hypothesis import HealthCheck, settings

PBT = settings(max_examples=200, deadline=1000, suppress_health_check=[HealthCheck.too_slow])
PBT_SLOW = settings(max_examples=50, deadline=5000, suppress_health_check=[HealthCheck.too_slow])  # statistical tests
