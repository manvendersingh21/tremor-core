"""Every model call of the terminal agent goes through SpeculativeCascadeRouter.generate().

`/tier` and the climb-on-failed-tests rule are done by choosing which [[tiers]] the pool may use for a
call. The router, its caches and its telemetry sink are the ones `config.build_router` makes.
"""
from __future__ import annotations

import copy
import pathlib
import tomllib
from dataclasses import dataclass, field

from .safety import ROOT  # also registers chimera_core

from chimera_core.config import build_router, load_config  # noqa: E402
from chimera_core.tiers import TierCfg, TierPool  # noqa: E402

LADDER = ["gpu-small", "cloud-deepseek"]  # Supabase cache first (the router), then the self-hosted 30B, then the 763B
MODES = {"auto": LADDER, "local": LADDER[:1], "gpu": LADDER[:1], "cloud": LADDER[1:]}  # local = gpu = the 30B
BIG = LADDER[-1]  # the 763B: the baseline for "$ saved" and "kept off the big model"
H200 = "gpu-h200"  # the same 30B on a Modal H200: joins the 30B step while warm (TierCfg.warm_only), never a step of its own


class _NoLocalCache:
    """The answer cache lives only in Supabase (PgVectorCache). This stands in for the router's SQLite exact cache."""

    def get(self, *a, **k):
        return None

    def put(self, *a, **k) -> None:
        return None


class RouterError(RuntimeError):
    pass


@dataclass
class Reply:
    text: str
    tier: str = ""
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    dollars: float = 0.0
    baseline_dollars: float = 0.0   # the same answer's tokens at the 763B price
    ms: float = 0.0
    cache: str | None = None        # "shared" when Supabase answered, else None
    cache_score: float | None = None  # best cosine seen in the Supabase lookup
    cache_status: str | None = None   # ok | timeout | down | unavailable | None (cache not configured)
    kept_tokens: int = 0            # tokens that never reached the big model
    tried: list[str] = field(default_factory=list)  # tiers called, in order (a climb shows here)

    @property
    def tokens(self) -> int:
        return self.tokens_in + self.tokens_out


def load_tiers(cfg) -> list[TierCfg]:
    if cfg.tiers:
        return list(cfg.tiers)
    ex = tomllib.loads((ROOT / "chimera.example.toml").read_text())
    return [TierCfg.model_validate(t) for t in ex.get("tiers", [])]


class Cascade:
    """Thin wrapper: pick the tiers for this call, call router.generate(), read its step events."""

    def __init__(self, config_path=None, namespace: str = "terminal", gpu_url: str | None = None,
                 semantic: bool = True, router=None, tiers: list[TierCfg] | None = None) -> None:
        if router is None:
            cfg = load_config(config_path)
            tiers = load_tiers(cfg)
            if gpu_url:
                tiers = [t.model_copy(update={"url": gpu_url}) if t.name == "gpu-small" else t for t in tiers]
            # No answer cache on this machine: the only cache is Supabase. build_router still makes SQLite
            # objects, so point them at ":memory:" (no file) and then drop them from the router.
            # shortcut: the cosine key is the whole prompt; the guard (numbers, negation, entities) is on because
            # two coding prompts can differ only in file text past the embedder's window.
            cfg = cfg.model_copy(update={"use_pool": True, "tiers": tiers})
            cfg.cache = cfg.cache.model_copy(update={"semantic": semantic, "path": ":memory:", "guard": True,
                                                     "backend": "postgres" if semantic else cfg.cache.backend})
            router = build_router(cfg)
            if getattr(router, "shared", None) is not None:
                try:  # open the DB connection now, so the first lookup fits its 300 ms budget
                    router.shared.ping()
                except Exception:  # noqa: BLE001  down: lookups report "unavailable" and the tiers answer
                    pass
            self.conf = cfg.thresholds.confidence
        else:
            self.conf = 0.85
        self.by_name = {t.name: t for t in (tiers or [])}
        self.router = copy.copy(router)
        self.router.exact, self.router.semantic = _NoLocalCache(), None
        self.router.cfg = router.cfg.model_copy(update={"namespace": namespace})
        self._pools: dict[tuple, TierPool] = {}

    def names(self, mode: str, floor: int = 0) -> list[str]:
        return MODES[mode][floor:] if mode == "auto" else MODES[mode]

    def _pool(self, names: list[str], forced: bool) -> TierPool:
        if "gpu-small" in names and H200 in self.by_name:  # the 30B step: the H200 copy first while warm
            names = [H200, *names]
        key = (tuple(names), forced)
        if key not in self._pools:
            # The 30B tries every task (failed tests climb); a forced tier answers any task. Lift the ceiling.
            ts = [t.model_copy(update={"max_complexity": 1.0})
                  for t in (self.by_name[n] for n in names if n in self.by_name)]
            self._pools[key] = TierPool(ts, min_confidence=self.conf)
        return self._pools[key]

    def generate(self, prompt: str, mode: str = "auto", floor: int = 0, on_event=None, key: str = "") -> Reply:
        names = self.names(mode, floor)
        r = copy.copy(self.router)
        r.pool = self._pool(names, forced=mode != "auto")
        if key:  # hash of the context files: same files and request share answers, other file text never does
            r.cfg = r.cfg.model_copy(update={"namespace": f"{self.router.cfg.namespace}:{key}"})
        events: list[tuple[str, dict]] = []

        def tap(step: str, data: dict) -> None:
            events.append((step, data))
            if on_event:
                on_event(step, data)

        try:
            res = r.generate(prompt, on_event=tap)
        except Exception as e:  # noqa: BLE001  AllTiersFailed, connection errors
            raise RouterError(f"{type(e).__name__}: no tier in {names} could answer") from e
        return self._reply(res, events, prompt)

    def _reply(self, res, events, prompt: str) -> Reply:
        final = next((d for s, d in reversed(events) if s == "final"), {})
        calls = [d for s, d in events if s == "call"]
        ok = [c for c in calls if c.get("ok")]
        big = self.by_name.get(BIG)
        cache = final.get("cache")
        sh = next((d for s, d in events if s == "cache_shared"), None)
        rep = Reply(text=res.text, tier=final.get("tier", ""), model=final.get("model", ""),
                    tokens_in=final.get("tokens_in", 0), tokens_out=final.get("tokens_out", 0),
                    dollars=float(final.get("dollars", 0.0)), ms=float(final.get("ms", 0.0)), cache=cache,
                    tried=[c["tier"] for c in calls],
                    cache_score=sh.get("score") if sh else None,
                    cache_status=("unavailable" if sh and sh.get("status") in ("timeout", "down") else sh.get("status") if sh else None))
        if cache:  # nothing was called: estimate the tokens the big model would have been sent
            a_in, a_out = max(len(prompt) // 4, 1), max(len(res.text) // 4, 1)
            rep.tokens_in = rep.tokens_out = 0
        else:
            last = ok[-1] if ok else {}
            a_in, a_out = last.get("tokens_in", 0), last.get("tokens_out", 0)
        if big is not None:
            rep.baseline_dollars = a_in / 1000 * big.cost_per_1k_in + a_out / 1000 * big.cost_per_1k_out
        rep.kept_tokens = 0 if rep.tier == BIG else a_in + a_out
        return rep
