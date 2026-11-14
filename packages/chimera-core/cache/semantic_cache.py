"""Tier 1b: semantic cache. Cosine similarity >= threshold returns the stored answer.

Storage is SQLite (embeddings as float32 blobs). This is brute-force search, fine up to
tens of thousands of entries. Swap `_search` for sqlite-vec or Qdrant when you outgrow it.
"""
from __future__ import annotations

import array
import math
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Callable, Protocol


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...


class OnnxMiniLMEmbedder:
    """all-MiniLM-L6-v2 via sentence-transformers (optional dependency)."""

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        from sentence_transformers import SentenceTransformer  # lazy: heavy import

        self._model = SentenceTransformer(model_name)

    def embed(self, text: str) -> list[float]:
        return [float(x) for x in self._model.encode(text, normalize_embeddings=True)]


def _norm(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class SemanticCache:
    def __init__(self, embedder: Embedder, threshold: float = 0.94, path: str = ":memory:",
                 guard: "Callable[[str, str, float], bool] | None" = None) -> None:
        self._embedder = embedder
        self.threshold = threshold
        self.guard = guard  # (query, cached_prompt, similarity) -> accept; see cache/guard.py. Off (None) by default.
        self.guarded_out = 0  # cosine hits the guard turned into misses
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS entries (id INTEGER PRIMARY KEY, namespace TEXT, "
            "prompt TEXT, response TEXT, emb BLOB)"
        )
        self._lock = threading.Lock()

    def put(self, prompt: str, response: str, namespace: str = "") -> None:
        emb = array.array("f", _norm(self._embedder.embed(prompt))).tobytes()
        with self._lock:
            self._db.execute(
                "INSERT INTO entries (namespace, prompt, response, emb) VALUES (?,?,?,?)",
                (namespace, prompt, response, emb),
            )
            self._db.commit()

    def purge(self, namespace: str) -> int:
        with self._lock:
            n = self._db.execute("DELETE FROM entries WHERE namespace = ?", (namespace,)).rowcount
            self._db.commit()
            return n

    def get(self, prompt: str, namespace: str = "") -> tuple[str, float] | None:
        """Return (response, similarity) for the best match at or above the threshold."""
        return self.lookup(prompt, namespace).hit

    def lookup(self, prompt: str, namespace: str = "") -> "Lookup":
        """Like get(), plus the best cosine seen (even below the threshold) and the guard verdict."""
        t0 = time.perf_counter()
        query = _norm(self._embedder.embed(prompt))
        with self._lock:
            rows = self._db.execute(
                "SELECT response, emb, prompt FROM entries WHERE namespace = ?", (namespace,)
            ).fetchall()
        best: tuple[str, float] | None = None
        best_sim, verdict = None, "off" if self.guard is None else None
        for response, blob, cached in rows:
            vec = array.array("f")
            vec.frombytes(blob)
            sim = sum(a * b for a, b in zip(query, vec))
            best_sim = sim if best_sim is None else max(best_sim, sim)
            if sim >= self.threshold and (best is None or sim > best[1]):
                if self.guard is not None and not self.guard(prompt, cached, sim):
                    self.guarded_out += 1
                    verdict = "rejected"
                    continue
                best = (response, sim)
                verdict = verdict if self.guard is None else "pass"
        return Lookup(best, best_sim, verdict, (time.perf_counter() - t0) * 1000)


@dataclass
class Lookup:
    """One cache lookup, for step events. `hit` is (response, similarity) or None."""
    hit: tuple[str, float] | None
    best_sim: float | None
    guard: str | None  # "pass" | "rejected" | "off" | None (no candidate reached the threshold)
    ms: float
    status: str = "ok"  # shared cache only: "ok" | "timeout" | "down"


class CachedEmbedder:
    """Remembers the last few embeddings so the router, the local and the shared cache embed a prompt once."""

    def __init__(self, inner: Embedder, size: int = 64) -> None:
        self._inner, self._size, self._memo = inner, size, {}  # type: ignore[var-annotated]
        self._lock = threading.Lock()

    def embed(self, text: str) -> list[float]:
        with self._lock:
            v = self._memo.get(text)
        if v is None:
            v = self._inner.embed(text)
            with self._lock:
                if len(self._memo) >= self._size:
                    self._memo.pop(next(iter(self._memo)))
                self._memo[text] = v
        return v
