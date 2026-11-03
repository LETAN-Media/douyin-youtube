import asyncio
import logging
import time
from collections import deque

from ..config import settings

logger = logging.getLogger("backend-youtube.ai_rate_limiter")


class AIRateLimiter:
    """Simple in-memory token-per-minute / requests-per-minute limiter."""

    def __init__(self, max_requests: int | None = None, max_tokens: int | None = None):
        self.max_requests = max_requests if max_requests is not None else settings.TOOLNET_MAX_REQUESTS_PER_MINUTE
        self.max_tokens = max_tokens if max_tokens is not None else settings.TOOLNET_MAX_TOKENS_PER_MINUTE
        self._req_times: deque[float] = deque()
        self._token_times: deque[tuple[float, int]] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int = 100) -> bool:
        async with self._lock:
            now = time.monotonic()
            window = 60.0
            while self._req_times and self._req_times[0] <= now - window:
                self._req_times.popleft()
            while self._token_times and self._token_times[0][0] <= now - window:
                self._token_times.popleft()
            used_tokens = sum(t for _, t in self._token_times)
            if len(self._req_times) >= self.max_requests or (used_tokens + tokens) > self.max_tokens:
                sleep_for = self._next_available(now, window)
                await asyncio.sleep(sleep_for)
                return await self.acquire(tokens)
            self._req_times.append(now)
            self._token_times.append((now, tokens))
            return True

    def _next_available(self, now: float, window: float) -> float:
        if self._req_times:
            return max(0.1, window - (now - self._req_times[0]))
        if self._token_times:
            oldest_ts, oldest_tokens = self._token_times[0]
            remaining = self.max_tokens - (sum(t for _, t in self._token_times) - oldest_tokens)
            return max(0.1, window - (now - oldest_ts))
        return 0.1
