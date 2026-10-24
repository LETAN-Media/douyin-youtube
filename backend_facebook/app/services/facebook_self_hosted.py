"""Facebook self-hosted API client.

Provider: facebook-data-api on VPS 38.127.216.174:8080
Chain:
  POST /v1/facebook/reels {"url": <page_url>}
      -> {"uid": <id>, "reels": [<reel_urls>], "total": <count>}

Only JSON is consumed. No HTML scraping, no browser, no downloads.
The API key never appears in logs or error messages.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass

import httpx

logger = logging.getLogger("backend-facebook.self-hosted")

AUTH_ERROR = "SELFHOSTED_AUTH_ERROR"
UPSTREAM_ERROR = "SELFHOSTED_UPSTREAM_ERROR"
TIMEOUT = "SELFHOSTED_TIMEOUT"
RESPONSE_INVALID = "SELFHOSTED_RESPONSE_INVALID"
END_OF_RESULTS = "END_OF_RESULTS"
SAFETY_LIMIT = "SAFETY_LIMIT"


class SelfHostedApiError(Exception):
    """Typed provider error. Never carries the API key."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass
class SelfHostedApiConfig:
    base_url: str
    api_key: str
    timeout: float = 60.0
    max_retries: int = 3
    max_reels: int = 5000


class FacebookSelfHostedClient:
    """Typed wrapper around self-hosted facebook-data-api. One client per scan."""

    def __init__(self, config: SelfHostedApiConfig) -> None:
        if not config.api_key:
            raise ValueError("API key is required")
        self.config = config

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self.config.api_key, "Content-Type": "application/json"}

    def _client(self, transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=transport,
            base_url=self.config.base_url,
            timeout=self.config.timeout,
            headers=self._headers(),
        )

    async def _post_json(
        self,
        client: httpx.AsyncClient,
        path: str,
        payload: dict,
    ) -> object:
        """POST with retries for transient failures only. Never logs the key."""
        last: SelfHostedApiError | None = None
        for attempt in range(self.config.max_retries):
            try:
                resp = await client.post(path, json=payload)
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last = SelfHostedApiError(TIMEOUT, f"Provider timeout: {type(exc).__name__}.", retryable=True)
            else:
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except ValueError:
                        raise SelfHostedApiError(
                            RESPONSE_INVALID, "Provider returned invalid JSON.", retryable=False
                        )
                snippet = (resp.text or "")[:300]
                if resp.status_code in (401, 403):
                    raise SelfHostedApiError(AUTH_ERROR, f"Provider auth failed (HTTP {resp.status_code}).", retryable=False)
                if 500 <= resp.status_code <= 599:
                    last = SelfHostedApiError(UPSTREAM_ERROR, f"Provider upstream error (HTTP {resp.status_code}).", retryable=True)
                else:
                    raise SelfHostedApiError(UPSTREAM_ERROR, f"Provider request failed (HTTP {resp.status_code}): {snippet}", retryable=False)
            await asyncio.sleep(min(2**attempt, 8) + random.uniform(0, 0.5))
        assert last is not None
        raise last

    async def fetch_reels(
        self,
        page_url: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> list[str]:
        """Fetch all reels from a Facebook page. Returns list of reel URLs."""
        async with self._client(transport) as client:
            data = await self._post_json(client, "/v1/facebook/reels", {"url": page_url})
        
        if not isinstance(data, dict):
            raise SelfHostedApiError(RESPONSE_INVALID, "Reels response is not an object.")
        
        reels = data.get("reels")
        if not isinstance(reels, list):
            raise SelfHostedApiError(RESPONSE_INVALID, "Reels response has no reels list.")
        
        return [str(url) for url in reels if isinstance(url, str)]
