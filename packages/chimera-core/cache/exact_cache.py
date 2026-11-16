"""Tier 1a: exact SHA-256 cache over a normalized prompt."""
from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
from collections import OrderedDict

_WS = re.compile(r"\s+")


def normalize(prompt: str) -> str:
    return _WS.sub(" ", prompt.strip()).lower()


def prompt_hash(prompt: str, namespace: str = "") -> str:
    # NUL is the separator: "a" + "b\x00c" would collide with "a\x00b" + "c". Refusing it keeps every other hash unchanged.
    if "\x00" in namespace:
        raise ValueError("namespace must not contain NUL")
    # surrogatepass: a lone surrogate (bad client input) still hashes instead of raising
    return hashlib.sha256(f"{namespace}\x00{normalize(prompt)}".encode("utf-8", "surrogatepass")).hexdigest()


class ExactCache:
    def __init__(self, max_entries: int = 4096, path: str | None = None) -> None:
        self._data: OrderedDict[str, str] = OrderedDict()
        self._ns: dict[str, str] = {}  # key -> namespace, so purge() can find in-memory entries
        self._max = max_entries
        self._lock = threading.Lock()
        # path: optional SQLite file so entries survive restarts (write-through; reads fall back to it).
        self._db = sqlite3.connect(path, check_same_thread=False) if path else None
        if self._db:
            self._db.execute("CREATE TABLE IF NOT EXISTS exact (key TEXT PRIMARY KEY, response TEXT, ns TEXT DEFAULT '')")
            if "ns" not in {r[1] for r in self._db.execute("PRAGMA table_info(exact)")}:
                self._db.execute("ALTER TABLE exact ADD COLUMN ns TEXT DEFAULT ''")  # files from before purge()

    def get(self, prompt: str, namespace: str = "") -> str | None:
        key = prompt_hash(prompt, namespace)
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                return self._data[key]
            if self._db:
                row = self._db.execute("SELECT response, ns FROM exact WHERE key = ?", (key,)).fetchone()
                if row:
                    self._data[key], self._ns[key] = row[0], row[1] or ""
                    return row[0]
        return None

    def put(self, prompt: str, response: str, namespace: str = "") -> None:
        key = prompt_hash(prompt, namespace)
        with self._lock:
            self._data[key] = response
            self._ns[key] = namespace
            self._data.move_to_end(key)
            if self._db:
                self._db.execute("INSERT OR REPLACE INTO exact (key, response, ns) VALUES (?, ?, ?)",
                                 (key, response, namespace))
                self._db.commit()
            while len(self._data) > self._max:
                self._ns.pop(self._data.popitem(last=False)[0], None)

    def purge(self, namespace: str) -> int:
        """Delete every entry stored under `namespace` (memory and SQLite). Returns the rows removed."""
        with self._lock:
            for k in [k for k, n in self._ns.items() if n == namespace]:
                self._data.pop(k, None)
                del self._ns[k]
            if not self._db:
                return 0
            n = self._db.execute("DELETE FROM exact WHERE ns = ?", (namespace,)).rowcount
            self._db.commit()
            return n

    def __bool__(self) -> bool:
        return True  # router does `exact or ExactCache()`; an empty cache must not be swapped out

    def __len__(self) -> int:
        return len(self._data)
