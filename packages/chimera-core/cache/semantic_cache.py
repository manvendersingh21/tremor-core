"""Tier 1b: semantic cache. Cosine similarity >= threshold returns the stored answer.

Storage is SQLite (embeddings as float32 blobs). This is brute-force search, fine up to
tens of thousands of entries. Swap `_search` for sqlite-vec or Qdrant when you outgrow it.
"""
from __future__ import annotations

import array
import math
import sqlite3
import threading
from typing import Protocol


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
    def __init__(self, embedder: Embedder, threshold: float = 0.94, path: str = ":memory:") -> None:
        self._embedder = embedder
        self.threshold = threshold
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

    def get(self, prompt: str, namespace: str = "") -> tuple[str, float] | None:
        """Return (response, similarity) for the best match at or above the threshold."""
        query = _norm(self._embedder.embed(prompt))
        with self._lock:
            rows = self._db.execute(
                "SELECT response, emb FROM entries WHERE namespace = ?", (namespace,)
            ).fetchall()
        best: tuple[str, float] | None = None
        for response, blob in rows:
            vec = array.array("f")
            vec.frombytes(blob)
            sim = sum(a * b for a, b in zip(query, vec))
            if sim >= self.threshold and (best is None or sim > best[1]):
                best = (response, sim)
        return best
