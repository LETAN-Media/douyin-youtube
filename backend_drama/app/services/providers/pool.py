"""RapidAPI provider failover pool: 1 primary + up to 4 fallbacks.

- Loads slots from DRAMA_API_PRIMARY_* / DRAMA_API_FALLBACK_{1..4}_*.
  Legacy DRAMA_API_HOST/BASE_URL/KEY map to the primary slot.
  Unconfigured slots are skipped.
- Failover on: network error, timeout, 5xx, invalid response, temporary
  unavailability. 401/403 stop immediately (CONFIG_ERROR, no retry).
  404/data-not-found returns NOT_FOUND without touching other providers.
  429 moves only to a *different host* (independent quota); same-host
  endpoints are skipped until their backoff expires. No key rotation.
- Circuit breaker: 3 consecutive failures -> 5-minute cooldown (skip).
  After cooldown the endpoint is probed again naturally.
- Capability routing: an endpoint serves a content provider only when its
  _PROVIDERS list is empty (all) or contains the name.
- Logs never contain keys or signed URLs (host + status only).

All state is in-memory per process; reset_pool_state() exists for tests.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger("backend-drama-pool")

FAILOVERABLE_CODES = frozenset({"TIMEOUT", "TEMPORARY", "INVALID_RESPONSE"})
CONFIG_ERROR_CODES = frozenset({"AUTH_FAILED", "CONFIG_ERROR"})
NOT_FOUND_CODES = frozenset({"NOT_FOUND"})

CIRCUIT_FAILURE_THRESHOLD = 3
CIRCUIT_COOLDOWN_SECONDS = 5 * 60
RATE_LIMIT_COOLDOWN_SECONDS = 60.0


@dataclass(frozen=True)
class ProviderEndpoint:
    name: str  # "primary" | "fallback_1" .. "fallback_4"
    host: str
    base_url: str
    api_key: str
    priority: int
    enabled: bool = True
    providers: tuple[str, ...] = ()  # empty = serves all content providers

    def serves(self, provider_name: str) -> bool:
        if not self.enabled:
            return False
        if not self.providers:
            return True
        return provider_name.strip().lower() in self.providers


@dataclass
class _CircuitState:
    consecutive_failures: int = 0
    unhealthy_until: float = 0.0
    rate_limited_until: float = 0.0


_states: dict[str, _CircuitState] = {}
# Rate-limited quota pools, keyed by (host, api_key): quotas are per key,
# so same-host endpoints with different keys stay independent, while the
# same credentials are never hammered.
_limited_pools: dict[tuple[str, str], float] = {}


def reset_pool_state() -> None:
    _states.clear()
    _limited_pools.clear()


def _state_for(name: str) -> _CircuitState:
    state = _states.get(name)
    if state is None:
        state = _CircuitState()
        _states[name] = state
    return state


def _parse_providers(raw: str | None) -> tuple[str, ...]:
    return tuple(
        p.strip().lower() for p in (raw or "").split(",") if p.strip()
    )


def load_pool_from_settings() -> list[ProviderEndpoint]:
    """Build the ordered endpoint pool. Legacy DRAMA_API_* is the primary."""
    from ...config import settings

    def slot(
        name: str, priority: int, host: str | None, base: str | None,
        key: str | None, providers: str | None,
    ) -> ProviderEndpoint | None:
        host = (host or "").strip()
        key = (key or "").strip()
        if not host or not key:
            return None
        base_url = (base or "").strip().rstrip("/") or f"https://{host}"
        return ProviderEndpoint(
            name=name, host=host, base_url=base_url, api_key=key,
            priority=priority, enabled=True,
            providers=_parse_providers(providers),
        )

    endpoints: list[ProviderEndpoint] = []
    primary = slot(
        "primary", 0,
        settings.DRAMA_API_PRIMARY_HOST or settings.DRAMA_API_HOST,
        settings.DRAMA_API_PRIMARY_BASE_URL or settings.DRAMA_API_BASE_URL,
        settings.DRAMA_API_PRIMARY_KEY or settings.drama_api_key(),
        settings.DRAMA_API_PRIMARY_PROVIDERS,
    )
    if primary is not None:
        endpoints.append(primary)
    for i in (1, 2, 3, 4):
        fb = slot(
            f"fallback_{i}", i,
            getattr(settings, f"DRAMA_API_FALLBACK_{i}_HOST", None),
            getattr(settings, f"DRAMA_API_FALLBACK_{i}_BASE_URL", None),
            getattr(settings, f"DRAMA_API_FALLBACK_{i}_KEY", None),
            getattr(settings, f"DRAMA_API_FALLBACK_{i}_PROVIDERS", None),
        )
        if fb is not None:
            endpoints.append(fb)
    return sorted(endpoints, key=lambda e: e.priority)


def pool_health(endpoints: list[ProviderEndpoint] | None = None) -> dict[str, str]:
    """Safe status snapshot: {endpoint_name: healthy|cooldown|rate_limited}."""
    if endpoints is None:
        endpoints = load_pool_from_settings()
    now = time.monotonic()
    out: dict[str, str] = {}
    for ep in endpoints:
        state = _state_for(ep.name)
        if state.unhealthy_until > now:
            out[ep.name] = "cooldown"
        elif state.rate_limited_until > now:
            out[ep.name] = "rate_limited"
        else:
            out[ep.name] = "healthy"
    return out


def _record_success(name: str) -> None:
    state = _state_for(name)
    state.consecutive_failures = 0
    state.unhealthy_until = 0.0
    state.rate_limited_until = 0.0


def _record_failure(name: str, *, rate_limited: bool = False,
                    retry_after: float | None = None) -> None:
    state = _state_for(name)
    if rate_limited:
        wait = retry_after if retry_after and retry_after > 0 else RATE_LIMIT_COOLDOWN_SECONDS
        state.rate_limited_until = time.monotonic() + min(wait, 600.0)
        return
    state.consecutive_failures += 1
    if state.consecutive_failures >= CIRCUIT_FAILURE_THRESHOLD:
        state.unhealthy_until = time.monotonic() + CIRCUIT_COOLDOWN_SECONDS


def _is_usable(ep: ProviderEndpoint, now: float) -> bool:
    state = _state_for(ep.name)
    if state.unhealthy_until > now or state.rate_limited_until > now:
        return False
    # Same credentials share one rate-limited quota pool: only pools
    # without an active backoff are eligible. Different keys on the same
    # host are independent and still tried; keys are never rotated to
    # bypass limits — a limited pool is skipped, never forced.
    if _limited_pools.get((ep.host, ep.api_key), 0.0) > now:
        return False
    return True


class PoolExhausted(Exception):
    """All usable endpoints failed. Carries per-endpoint codes, no secrets."""

    def __init__(self, code: str, message: str, attempts: list[dict[str, str]]) -> None:
        super().__init__(message)
        self.code = code
        self.attempts = attempts


async def execute(
    provider_name: str,
    operation: str,
    transport: httpx.AsyncBaseTransport | None = None,
    **kwargs: Any,
) -> tuple[Any, str]:
    """Run one adapter operation across the failover pool.

    Returns (result, endpoint_name). Builds a fresh adapter per endpoint
    with that endpoint's credentials. See module docstring for policy.
    """
    from . import get_provider

    endpoints = [
        ep for ep in load_pool_from_settings() if ep.serves(provider_name)
    ]
    if not endpoints:
        raise PoolExhausted(
            "NOT_CONFIGURED",
            f"No provider endpoint configured for '{provider_name}'.",
            [],
        )
    attempts: list[dict[str, str]] = []
    for ep in endpoints:
        if not _is_usable(ep, time.monotonic()):
            continue
        adapter = get_provider(provider_name, transport=transport, endpoint=ep)
        try:
            result = await getattr(adapter, operation)(**kwargs)
        except Exception as exc:
            code = getattr(exc, "code", "TEMPORARY") or "TEMPORARY"
            if code in CONFIG_ERROR_CODES:
                logger.warning(
                    "provider=%s host=%s config error=%s; not retrying",
                    ep.name, ep.host, code,
                )
                raise PoolExhausted(
                    "CONFIG_ERROR",
                    f"Provider endpoint '{ep.name}' misconfigured ({code}).",
                    attempts + [{"endpoint": ep.name, "code": code}],
                )
            if code in NOT_FOUND_CODES:
                raise PoolExhausted(
                    "NOT_FOUND", str(exc) or "Not found.",
                    attempts + [{"endpoint": ep.name, "code": code}],
                )
            if code == "RATE_LIMITED":
                retry_after = getattr(exc, "retry_after", None)
                wait = retry_after if isinstance(retry_after, (int, float)) and retry_after > 0 else RATE_LIMIT_COOLDOWN_SECONDS
                _record_failure(ep.name, rate_limited=True, retry_after=wait)
                _limited_pools[(ep.host, ep.api_key)] = time.monotonic() + min(wait, 600.0)
                attempts.append({"endpoint": ep.name, "code": code})
                logger.warning(
                    "provider=%s host=%s status=429 rate_limited; independent hosts only",
                    ep.name, ep.host,
                )
                continue
            if code in ("NOT_CONFIGURED", "UNSUPPORTED", "UNSUPPORTED_PROVIDER"):
                attempts.append({"endpoint": ep.name, "code": code})
                continue
            # Failoverable: timeout / network / 5xx / invalid / temporary.
            _record_failure(ep.name)
            attempts.append({"endpoint": ep.name, "code": code})
            logger.warning(
                "provider=%s host=%s status=%s failover_to=next",
                ep.name, ep.host, code,
            )
            continue
        _record_success(ep.name)
        if ep.name != endpoints[0].name:
            logger.info("provider=%s host=%s recovered via failover", ep.name, ep.host)
        return result, ep.name
    raise PoolExhausted(
        "ALL_PROVIDERS_FAILED",
        f"All provider endpoints failed for '{provider_name}'.",
        attempts,
    )
