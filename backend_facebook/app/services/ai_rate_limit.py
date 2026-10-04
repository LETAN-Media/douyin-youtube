"""Local rate limiter for ToolNet AI calls (Task 8A follow-up).

Sliding 60s windows for request count AND token usage. Guards the account
before hitting the provider (30 req/min, 8000 tokens/min defaults).
In-memory per instance; reservations keep accounting accurate across retries.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Callable


class RateLimitExceeded(Exception):
    """Raised when a call would exceed the local per-minute budget."""

    def __init__(self, message: str, retry_after_s: float = 60.0) -> None:
        super().__init__(message)
        self.retry_after_s = max(0.0, retry_after_s)


class AiRateLimiter:
    def __init__(
        self,
        max_requests_per_minute: int = 30,
        max_tokens_per_minute: int = 8000,
        window_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_requests = max(1, int(max_requests_per_minute))
        self.max_tokens = max(1, int(max_tokens_per_minute))
        self.window_s = window_s
        self._clock = clock
        self._lock = asyncio.Lock()
        self._requests: deque[float] = deque()
        self._tokens: deque[tuple[float, int]] = deque()

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_s
        while self._requests and self._requests[0] <= cutoff:
            self._requests.popleft()
        while self._tokens and self._tokens[0][0] <= cutoff:
            self._tokens.popleft()

    def _used_tokens(self) -> int:
        return sum(t for _, t in self._tokens)

    async def reserve(self, estimated_tokens: int) -> None:
        """Reserve budget for one call; raises RateLimitExceeded if over budget."""
        now = self._clock()
        async with self._lock:
            self._prune(now)
            if len(self._requests) >= self.max_requests:
                oldest = self._requests[0]
                raise RateLimitExceeded(
                    f"Local AI rate limit: {self.max_requests} requests/min exceeded.",
                    retry_after_s=(oldest + self.window_s) - now,
                )
            if self._used_tokens() + max(0, int(estimated_tokens)) > self.max_tokens:
                oldest = self._tokens[0][0] if self._tokens else now
                raise RateLimitExceeded(
                    f"Local AI rate limit: {self.max_tokens} tokens/min exceeded.",
                    retry_after_s=(oldest + self.window_s) - now,
                )
            self._requests.append(now)
            self._tokens.append((now, max(0, int(estimated_tokens))))

    async def settle(self, estimated_tokens: int, actual_tokens: int | None) -> None:
        """Replace the estimate with the actual usage (or drop it if unknown)."""
        if actual_tokens is None:
            actual_tokens = 0
        async with self._lock:
            now = self._clock()
            self._prune(now)
            for i in range(len(self._tokens) - 1, -1, -1):
                ts, tok = self._tokens[i]
                if tok == max(0, int(estimated_tokens)):
                    self._tokens[i] = (ts, max(0, int(actual_tokens)))
                    break
            self._prune(now)

    async def release(self, estimated_tokens: int) -> None:
        """Drop a reservation (call never consumed provider budget)."""
        await self.settle(estimated_tokens, 0)

    def snapshot(self) -> dict:
        now = self._clock()
        self._prune(now)
        return {
            "requests_used": len(self._requests),
            "tokens_used": self._used_tokens(),
            "max_requests": self.max_requests,
            "max_tokens": self.max_tokens,
        }


_shared_limiter: AiRateLimiter | None = None
_shared_key: tuple | None = None


def get_shared_limiter(max_requests: int, max_tokens: int) -> AiRateLimiter:
    global _shared_limiter, _shared_key
    key = (int(max_requests), int(max_tokens))
    if _shared_limiter is None or _shared_key != key:
        _shared_limiter = AiRateLimiter(key[0], key[1])
        _shared_key = key
    return _shared_limiter


def reset_shared_limiter() -> None:
    global _shared_limiter, _shared_key
    _shared_limiter = None
    _shared_key = None
