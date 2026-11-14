"""Feed the HUD with router telemetry. Default: fake backends (no network, no keys). --real: live backends.

    python apps/phantom-phone/hud-web/demo.py [--real] [--interval 1.2] [--loops 0]
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import pathlib
import random
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import conftest  # noqa: E402,F401  (exposes chimera_core)

from chimera_core import RouterConfig, SpeculativeCascadeRouter, TelemetryTracker  # noqa: E402
from chimera_core.cache.semantic_cache import SemanticCache  # noqa: E402
from chimera_core.inference.cloud_verifier import CloudVerifier  # noqa: E402
from chimera_core.inference.local_draft import DraftResult  # noqa: E402
from chimera_core.inference.telemetry import Telemetry, TierUsage  # noqa: E402

OUT = pathlib.Path(os.environ.get("HUD_TELEMETRY", pathlib.Path(__file__).parent / "telemetry.jsonl"))


# ---- fake backends (same shape as tests/test_router.py) ----------------------
class FakeLocal:
    """Confident on most prompts, shaky on some. Confidence is seeded by the prompt."""

    def complete(self, prompt, max_tokens=256, system=None):
        rng = random.Random(hashlib.sha256(prompt.encode()).hexdigest())
        conf = 0.97 if rng.random() < 0.75 else 0.6
        n = rng.randint(8, 60)
        time.sleep(rng.uniform(0.05, 0.4))
        return DraftResult(text=f"local answer to: {prompt[:40]}", token_ids=list(range(n)),
                           logprobs=[math.log(conf)] * n, mean_confidence=conf)


class FakeCloud:
    def complete(self, prompt, max_tokens):
        time.sleep(random.uniform(0.4, 1.5))
        return "cloud answer " * random.randint(10, 80)

    def score_tokens(self, prompt_ids, draft_ids):
        return [math.log(random.uniform(0.5, 1.0)) for _ in draft_ids]  # target mostly agrees

    def sample_next(self, ctx):
        return 99


class FakeTokenizer:
    def encode(self, text):
        return [ord(c) for c in text[:64]]

    def decode(self, ids):
        return "verified answer " * max(len(ids) // 8, 1)


class WordEmbedder:
    def embed(self, text):
        v = [0.0] * 64
        for w in text.lower().split():
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1.0
        return v


# ---- demo per_tier data ------------------------------------------------------
# The router does not fill per_tier yet, so the demo invents a realistic split. Every number here is "demo".
CRUSOE_MODELS = {"Qwen/Qwen3.8-27B": (0.25, 2.0), "openai/gpt-oss-120b": (0.15, 0.6)}  # $ per M tokens in, out
_rng = random.Random(7)
_targets = itertools.cycle(["gpu_small", "gpu_large", "crusoe", "gpu_small", "crusoe"])  # handoffs are rare; cycle so every tier shows


def _use(model: str, device: str, tin: int, tout: int, ms: float, usd=(0.0, 0.0)) -> TierUsage:
    return TierUsage(model=model, device=device, input_tokens=tin, output_tokens=tout, latency_ms=round(ms),
                     dollars=(tin * usd[0] + tout * usd[1]) / 1e6)


def with_per_tier(ev: Telemetry) -> Telemetry:
    """Attach an invented per-model split (and re-label tier_used to match) so the HUD ledger fills."""
    if ev.tier_used.endswith("_cache"):
        return ev
    r, tier, out = _rng, ev.tier_used, ev.model_copy()
    mac = lambda tin, tout, ms: _use("Qwen2.5-3B-Instruct q4_k_m", "Mac", tin, tout, ms)  # noqa: E731
    if tier == "local":
        if r.random() < 0.4:
            out.per_tier = {"phone_3b": _use("Gemma-3-1B-it", "Phone", r.randint(30, 90), max(ev.local_tokens, 8), ev.latency_ms)}
        else:
            out.per_tier = {"mac_3b": mac(r.randint(30, 120), max(ev.local_tokens, 8), ev.latency_ms)}
    elif tier == "cloud_verified":
        model = r.choice(list(CRUSOE_MODELS))
        n = max(ev.local_tokens, 8)
        out.per_tier = {"mac_3b": mac(r.randint(40, 110), n, ev.latency_ms * .3),
                        "crusoe": _use(model, "Crusoe", n + 60, max(ev.cloud_tokens, 4), ev.latency_ms * .7, CRUSOE_MODELS[model])}
    else:  # cloud_handoff: a short brief on the Mac, then the answer on a bigger model
        brief = min(max(ev.local_tokens, 20), 200)
        answer = r.randint(80, 320)
        pick = next(_targets)
        per = {"mac_3b": mac(r.randint(60, 160), brief, ev.latency_ms * .2)}
        if pick == "gpu_small":
            per[pick] = _use("qwen3:30b-instruct", "V100 GPU", brief + 70, answer, ev.latency_ms * .8)
            out.tier_used = "gpu"
        elif pick == "gpu_large":
            per[pick] = _use("Qwen3-235B-A22B (future)", "GPU", brief + 70, answer, ev.latency_ms * .9)
            out.tier_used = "gpu"
        else:
            model = r.choice(list(CRUSOE_MODELS))
            per[pick] = _use(model, "Crusoe", brief + 70, answer, ev.latency_ms * .8, CRUSOE_MODELS[model])
            out.tier_used = "top"
        out.per_tier = per
    return out


def demo_sink(path: str):
    write = TelemetryTracker.jsonl_sink(path)
    return lambda ev: write(with_per_tier(ev))


def build_router(real: bool, sink) -> SpeculativeCascadeRouter:
    tracker = TelemetryTracker(sinks=[sink])
    if not real:
        return SpeculativeCascadeRouter(
            FakeLocal(), CloudVerifier(FakeCloud()), semantic=SemanticCache(WordEmbedder()),
            tracker=tracker, config=RouterConfig(), tokenizer=FakeTokenizer())
    from chimera_core.cache.semantic_cache import OnnxMiniLMEmbedder
    from chimera_core.inference.cloud_verifier import CrusoeBackend
    from chimera_core.inference.local_draft import LlamaCppBackend

    env = ROOT / ".env"
    if env.is_file():
        for line in env.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    return SpeculativeCascadeRouter(
        LlamaCppBackend(), CloudVerifier(CrusoeBackend()), semantic=SemanticCache(OnnxMiniLMEmbedder()),
        tracker=tracker, config=RouterConfig())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", action="store_true", help="use llama-server on :8080 and Crusoe (needs CRUSOE_API_KEY)")
    ap.add_argument("--interval", type=float, default=1.2, help="seconds between calls")
    ap.add_argument("--loops", type=int, default=0, help="passes over the prompts (0 = forever)")
    args = ap.parse_args()

    lines = (ROOT / "bench" / "prompts.jsonl").read_text().splitlines()
    prompts = [json.loads(x)["prompt"] for x in lines if x.strip()]
    source = "real backends" if args.real else "demo (simulated backends, invented per-model split)"
    OUT.write_text(json.dumps({"_meta": {"source": source}}) + "\n")  # fresh run: reset the HUD file
    router = build_router(args.real, TelemetryTracker.jsonl_sink(str(OUT)) if args.real else demo_sink(str(OUT)))
    print(f"{source}: writing {OUT}. Ctrl-C to stop.")
    n = 0
    try:
        while args.loops == 0 or n < args.loops:
            for p in prompts:
                router.generate(p)
                time.sleep(args.interval)
            n += 1
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
