"""Prometheus text exposition, in memory. Resets on restart."""
from __future__ import annotations

import threading

BUCKETS = (50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000, 90000)


def _esc(v: str) -> str:
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _labels(**kw) -> str:
    return "{" + ",".join(f'{k}="{_esc(v)}"' for k, v in kw.items()) + "}"


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: dict[tuple, list[float]] = {}   # (tenant, tier) -> [calls, tokens, dollars, lat_sum, *buckets]
        self._events: dict[tuple, int] = {}          # (name, tenant, extra) -> count

    def observe(self, tenant: str, tier: str, tokens_saved: int, dollars_saved: float, latency_ms: float) -> None:
        with self._lock:
            row = self._calls.setdefault((tenant, tier), [0.0] * (4 + len(BUCKETS) + 1))
            row[0] += 1
            row[1] += tokens_saved
            row[2] += dollars_saved
            row[3] += latency_ms
            for i, le in enumerate(BUCKETS):
                if latency_ms <= le:
                    row[4 + i] += 1
            row[-1] += 1  # +Inf

    def event(self, name: str, tenant: str, extra: str = "") -> None:
        with self._lock:
            self._events[(name, tenant, extra)] = self._events.get((name, tenant, extra), 0) + 1

    def render(self) -> str:
        with self._lock:
            calls = {k: list(v) for k, v in self._calls.items()}
            events = dict(self._events)
        out: list[str] = []

        def block(name: str, kind: str, help_: str, idx: int) -> None:
            out.append(f"# HELP {name} {help_}\n# TYPE {name} {kind}")
            for (t, tier), row in sorted(calls.items()):
                out.append(f"{name}{_labels(tenant=t, tier=tier)} {row[idx]:g}")

        block("chimera_calls_total", "counter", "Answered calls.", 0)
        block("chimera_tokens_saved_total", "counter", "Estimated tokens not sent to the top tier.", 1)
        block("chimera_dollars_saved_total", "counter", "Estimated dollars saved at list price.", 2)
        n = "chimera_latency_ms"
        out.append(f"# HELP {n} Router latency per call in milliseconds.\n# TYPE {n} histogram")
        for (t, tier), row in sorted(calls.items()):
            for i, le in enumerate(BUCKETS):
                out.append(f"{n}_bucket{_labels(tenant=t, tier=tier, le=le)} {row[4 + i]:g}")
            out.append(f"{n}_bucket{_labels(tenant=t, tier=tier, le='+Inf')} {row[-1]:g}")
            out.append(f"{n}_sum{_labels(tenant=t, tier=tier)} {row[3]:g}")
            out.append(f"{n}_count{_labels(tenant=t, tier=tier)} {row[0]:g}")
        for name, label, help_ in (("rate_limited", "", "Calls rejected with 429."),
                                   ("errors", "code", "Failed calls by error code."),
                                   ("fallbacks", "path", "Calls answered one tier down after a backend failure.")):
            out.append(f"# HELP chimera_{name}_total {help_}\n# TYPE chimera_{name}_total counter")
            for (e, t, x), c in sorted(events.items()):
                if e == name:
                    out.append(f"chimera_{name}_total{_labels(tenant=t, **({label: x} if label else {}))} {c}")
        return "\n".join(out) + "\n"
