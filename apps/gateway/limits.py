"""Per-key token bucket."""
from __future__ import annotations

import threading
import time
from typing import Callable


class RateLimiter:
    def __init__(self, rate_per_min: float, burst: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.rate, self.burst, self._clock = rate_per_min / 60.0, float(burst), clock
        self._state: dict[int, tuple[float, float]] = {}  # key id -> (tokens, last)
        self._lock = threading.Lock()

    def acquire(self, key_id: int) -> float:
        """0.0 if the call may go ahead, else seconds until a token is available."""
        now = self._clock()
        with self._lock:
            tokens, last = self._state.get(key_id, (self.burst, now))
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            if tokens >= 1:
                self._state[key_id] = (tokens - 1, now)
                return 0.0
            self._state[key_id] = (tokens, now)
            return (1 - tokens) / self.rate if self.rate > 0 else 60.0
