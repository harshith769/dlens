"""Per-provider requests-per-minute limiter (sliding 60 s window, injectable clock)."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

RPM_LIMITS: dict[str, int | None] = {"gemini": 15, "groq": 30, "ollama": None}
WINDOW_SECONDS = 60.0


class RateLimiter:
    def __init__(
        self,
        rpm: int | None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.rpm = rpm
        self._clock = clock
        self._sleep = sleep
        self._sent: deque[float] = deque()

    def acquire(self) -> None:
        """Block until one more request fits in the window, then record it."""
        if self.rpm is None:
            return
        while True:
            now = self._clock()
            while self._sent and self._sent[0] <= now - WINDOW_SECONDS:
                self._sent.popleft()
            if len(self._sent) < self.rpm:
                self._sent.append(now)
                return
            self._sleep(self._sent[0] + WINDOW_SECONDS - now)
