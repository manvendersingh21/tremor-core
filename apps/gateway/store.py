"""API keys (SHA-256 hashes only) and the audit log, in one SQLite file."""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import sqlite3
import threading
import time
from typing import NamedTuple

TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,62}$")


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class Key(NamedTuple):
    id: int
    tenant: str


def _connect(path: str) -> sqlite3.Connection:
    if path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    db = sqlite3.connect(path, check_same_thread=False, timeout=10)
    if path != ":memory:":
        os.chmod(path, 0o600)
    return db


class KeyStore:
    def __init__(self, path: str) -> None:
        self._db, self._lock = _connect(path), threading.Lock()
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS keys (id INTEGER PRIMARY KEY, tenant TEXT NOT NULL, "
            "key_hash TEXT NOT NULL UNIQUE, prefix TEXT NOT NULL, created_at REAL NOT NULL, revoked_at REAL)"
        )
        self._db.commit()

    def create(self, tenant: str) -> tuple[int, str]:
        """Returns (id, raw key). The raw key is not stored and cannot be shown again."""
        if not TENANT_RE.match(tenant):
            raise ValueError("tenant must match [a-z0-9][a-z0-9_.-]{0,62}")
        raw = "chm_" + secrets.token_urlsafe(32)
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO keys (tenant, key_hash, prefix, created_at) VALUES (?,?,?,?)",
                (tenant, hash_key(raw), raw[:8], time.time()),
            )
            self._db.commit()
        return cur.lastrowid, raw

    def lookup(self, raw: str) -> Key | None:
        with self._lock:
            row = self._db.execute(
                "SELECT id, tenant FROM keys WHERE key_hash = ? AND revoked_at IS NULL", (hash_key(raw),)
            ).fetchone()
        return Key(*row) if row else None

    def list(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, tenant, prefix, created_at, revoked_at FROM keys ORDER BY id").fetchall()
        return [{"id": i, "tenant": t, "prefix": p, "created_at": c, "revoked": r is not None}
                for i, t, p, c, r in rows]

    def revoke(self, tenant: str | None = None, key_id: int | None = None) -> int:
        if (tenant is None) == (key_id is None):
            raise ValueError("give exactly one of tenant or key_id")
        col, val = ("tenant", tenant) if tenant is not None else ("id", key_id)
        with self._lock:
            n = self._db.execute(
                f"UPDATE keys SET revoked_at = ? WHERE {col} = ? AND revoked_at IS NULL", (time.time(), val)
            ).rowcount
            self._db.commit()
        return n


class AuditLog:
    """One row per answered call. No prompt or answer text."""

    def __init__(self, path: str) -> None:
        self._db, self._lock = _connect(path), threading.Lock()
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, ts REAL, request_id TEXT, tenant TEXT, "
            "tier TEXT, tokens_saved INTEGER, cloud_tokens INTEGER, dollars_saved REAL, latency_ms REAL)"
        )
        self._db.commit()

    def record(self, request_id: str, tenant: str, tel) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO audit (ts, request_id, tenant, tier, tokens_saved, cloud_tokens, dollars_saved, "
                "latency_ms) VALUES (?,?,?,?,?,?,?,?)",
                (time.time(), request_id, tenant, tel.tier_used, tel.tokens_saved, tel.cloud_tokens,
                 tel.dollars_saved, tel.latency_ms),
            )
            self._db.commit()

    def rows(self, tenant: str | None = None) -> list[tuple]:
        q, args = "SELECT tenant, tier, tokens_saved, cloud_tokens, dollars_saved, latency_ms FROM audit", ()
        if tenant:
            q, args = q + " WHERE tenant = ?", (tenant,)
        with self._lock:
            return self._db.execute(q, args).fetchall()
