"""Retry once on cloud 429/5xx/network errors, then answer from one tier down."""
from __future__ import annotations

import contextvars
import time
import urllib.error

# The request handler sets this to a list; each fallback appends (from_tier, to_tier).
FALLBACKS: contextvars.ContextVar[list | None] = contextvars.ContextVar("chimera_fallbacks", default=None)


def retriable(e: Exception) -> bool:
    if isinstance(e, urllib.error.HTTPError):
        return e.code == 429 or e.code >= 500
    return isinstance(e, (urllib.error.URLError, TimeoutError, ConnectionError))


class Resilient:
    def __init__(self, backend, fallback, name: str, fallback_name: str, backoff_s: float = 1.0,
                 sleep=time.sleep) -> None:
        self.backend, self.fallback, self.name, self.fallback_name = backend, fallback, name, fallback_name
        self.backoff_s, self._sleep = backoff_s, sleep

    def complete(self, prompt: str, max_tokens: int) -> str:
        try:
            return self.backend.complete(prompt, max_tokens)
        except Exception as e:  # noqa: BLE001
            no_key = isinstance(e, RuntimeError) and "API_KEY" in str(e)
            if not (retriable(e) or no_key):
                raise
            if retriable(e):
                self._sleep(self.backoff_s)
                try:
                    return self.backend.complete(prompt, max_tokens)
                except Exception as e2:  # noqa: BLE001
                    if not retriable(e2):
                        raise
        log = FALLBACKS.get()
        if log is not None:
            log.append((self.name, self.fallback_name))
        return self.fallback(prompt, max_tokens)
