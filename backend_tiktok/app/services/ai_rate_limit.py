"""Rate limiter for ToolNet / AI API calls."""

import asyncio
import logging
import time

logger = logging.getLogger("backend-tiktok.services.ai_rate_limit")


class ToolNetRateLimiter:
    """Sliding-window rate limiter for request count and token budget."""

    def __init__(
        self,
        requests_per_minute: int = 30,
        tokens_per_minute: int = 8000,
    ) -> None:
        self._req_limit = requests_per_minute
        self._tok_limit = tokens_per_minute
        self._req_times: list[float] = []
        self._tok_times: list[tuple[float, int]] = []
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int = 500) -> None:
        async with self._lock:
            now = time.time()
            self._req_times = [t for t in self._req_times if now - t < 60]
            self._tok_times = [(t, tk) for t, tk in self._tok_times if now - t < 60]

            token_usage = sum(tk for _, tk in self._tok_times)
            wait = 0.0
            if len(self._req_times) >= self._req_limit:
                oldest = self._req_times[0]
                wait = max(wait, 60 - (now - oldest) + 0.1)
            if token_usage + tokens > self._tok_limit:
                oldest_t, oldest_tk = self._tok_times[0]
                wait = max(wait, 60 - (now - oldest_t) + 0.1)

            if wait > 0:
                logger.info("Rate limit: waiting %.1fs", wait)
                await asyncio.sleep(wait)
                now = time.time()

            self._req_times.append(now)
            self._tok_times.append((now, tokens))
