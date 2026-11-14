"""Tier 1a: exact SHA-256 cache over a normalized prompt."""
from __future__ import annotations

import hashlib
import re
import threading
from collections import OrderedDict

_WS = re.compile(r"\s+")


def normalize(prompt: str) -> str:
    return _WS.sub(" ", prompt.strip()).lower()


def prompt_hash(prompt: str, namespace: str = "") -> str:
    return hashlib.sha256(f"{namespace}\x00{normalize(prompt)}".encode()).hexdigest()


class ExactCache:
    def __init__(self, max_entries: int = 4096) -> None:
        self._data: OrderedDict[str, str] = OrderedDict()
        self._max = max_entries
        self._lock = threading.Lock()

    def get(self, prompt: str, namespace: str = "") -> str | None:
        key = prompt_hash(prompt, namespace)
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                return self._data[key]
        return None

    def put(self, prompt: str, response: str, namespace: str = "") -> None:
        key = prompt_hash(prompt, namespace)
        with self._lock:
            self._data[key] = response
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def __len__(self) -> int:
        return len(self._data)
