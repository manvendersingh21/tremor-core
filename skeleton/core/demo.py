"""Demo mode: the same router and cache code as live, with the network parts swapped for stand-ins.

- MemStore: the Supabase cache table as a Python list (same Store interface as PgStore).
- HashEmbedder: content words hashed into 4096 numbers (live uses all-MiniLM-L6-v2). It knows no synonyms.
- stub models: fn(prompt) -> answer per tier name; "" means "I don't know", and the pool climbs.
Numbers from demo mode are labelled demo everywhere they are shown.
"""
from __future__ import annotations

import concurrent.futures as cf
import re
import threading
import zlib
from typing import Callable

from chimera_core.cache.guard import make_guard
from chimera_core.cache.pgvector_cache import PgVectorCache
from chimera_core.router import SpeculativeCascadeRouter

DIM = 4096  # 256 let "diaper" and "rice" share a slot: a false cache hit
# Words that do not change what a shopper or coder asks. Question words (where, when, how, what) stay.
STOP = set("a an the is are am be do does did i you we me my our your of to in on at for it this that there any "
           "can could would please tell find locate get have has sell carry stock some".split())


def words(text: str) -> list[str]:
    """Content words, lowercased, plural s dropped: 'Where are the eggs?' -> ['where', 'egg']."""
    out = []
    for w in re.findall(r"[a-z0-9]+", text.lower().replace("'", "").replace("\u2019", "")):
        if w not in STOP:
            out.append(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w)
    return out


class HashEmbedder:
    """Bag of content words, hashed. Two prompts with the same content words score 1.0."""

    def embed(self, text: str) -> list[float]:
        v = [0.0] * DIM
        for w in words(text):
            v[zlib.crc32(w.encode()) % DIM] += 1.0
        return v


class MemStore:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self._lock = threading.Lock()

    def lookup(self, tenant, ns, h, emb, k):
        with self._lock:
            rows = [r for r in self.rows if r["tenant"] == tenant and r["ns"] == ns]
        exact = next(((r["id"], r["answer"]) for r in reversed(rows) if r["h"] == h and r["verified"]), None)
        near = sorted(((r["id"], r["answer"], sum(a * b for a, b in zip(emb, r["emb"])), r["verified"], r["text"])
                       for r in rows), key=lambda x: -x[2])
        return exact, near[:k]

    def insert(self, tenant, ns, h, text, emb, answer, meta):
        with self._lock:
            self.rows.append({"id": len(self.rows) + 1, "tenant": tenant, "ns": ns, "h": h, "text": text,
                              "emb": emb, "answer": answer, "verified": meta.get("verified", True)})
            return len(self.rows)

    def touch(self, *a) -> None: ...
    def event(self, *a) -> None: ...
    def signal(self, *a) -> None: ...
    def set_verified(self, *a) -> None: ...

    def purge(self, tenant, ns) -> int:
        with self._lock:
            n = len(self.rows)
            self.rows = [r for r in self.rows if not (r["tenant"] == tenant and ns in (None, r["ns"]))]
            return n - len(self.rows)


def demo_router() -> SpeculativeCascadeRouter:
    """The product cache settings (threshold 0.97, guard, normalized prompts) over MemStore."""
    emb = HashEmbedder()
    shared = PgVectorCache(emb, MemStore(), threshold=0.97, store_text=True, normalize=True, guard=make_guard(),
                           budget_s=5.0)
    # one write worker: flush() then waits for every queued insert (with two, a no-op can finish first)
    shared._wpool.shutdown(wait=False)
    shared._wpool = cf.ThreadPoolExecutor(max_workers=1, thread_name_prefix="demo-cache-w")
    return SpeculativeCascadeRouter(None, exact=False, shared=shared, embedder=emb)


def stub_factory(models: dict[str, Callable[[str], str]]):
    """TierPool backend_factory: each tier answers with its stub (default: a fixed demo line)."""
    def make(t):
        fn = models.get(t.name) or (lambda p, name=t.name: f"[demo {name} answer]")

        class _Stub:
            @staticmethod
            def complete(prompt: str, n: int):
                text = fn(prompt) or ""
                return text, max(len(prompt) // 4, 1), len(text) // 4, None

        return _Stub()
    return make
