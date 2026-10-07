"""Multi-upstream failover: 1 primary + up to 4 fallbacks.

Separates two concepts that must not be confused:

- Content provider (starshort, dramabox, ...): WHAT catalog is served.
  Implemented by adapters; output is always normalized.
- Upstream vendor (Short Drama Pro, ReelShort Unofficial, ...): WHO serves
  the HTTP API. One content provider may be served by several upstreams.

Flow: Scanner -> content adapter -> UpstreamRouter (this pool) ->
primary upstream -> fallback upstreams -> normalize -> DB.

- Loads slots from DRAMA_API_PRIMARY_* / DRAMA_API_FALLBACK_{1..4}_*.
  Legacy DRAMA_API_HOST/BASE_URL/KEY map to the primary slot.
  Unconfigured slots are skipped. Optional _NAME overrides the slot name.
- Failover on: network error, timeout, 5xx, invalid response, temporary
  unavailability. 401/403 stop immediately (auth/subscription error, no
  retry, no spam). 404/data-not-found returns NOT_FOUND without touching
  other upstreams. 429 cools down only its own (host, key) pool and moves
  to independent credentials. No key rotation to bypass limits.
- Circuit breaker per upstream: CLOSED -> 3 consecutive failures -> OPEN
  (5-minute cooldown, skipped) -> HALF_OPEN (single probe after cooldown)
  -> CLOSED on success or OPEN again on failure.
- Capability routing: an upstream serves a content provider only when its
  _PROVIDERS list is empty (all) or contains the name.
- Logs and health snapshots never contain keys or signed URLs (host +
  status/code only).
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger("backend-drama-pool")

FAILOVERABLE_CODES = frozenset({"TIMEOUT", "TEMPORARY", "INVALID_RESPONSE"})
CONFIG_ERROR_CODES = frozenset({"AUTH_FAILED", "SUBSCRIPTION_ERROR", "CONFIG_ERROR"})
NOT_FOUND_CODES = frozenset({"NOT_FOUND"})

CIRCUIT_FAILURE_THRESHOLD = 3
CIRCUIT_COOLDOWN_SECONDS = 5 * 60
RATE_LIMIT_COOLDOWN_SECONDS = 60.0


@dataclass(frozen=True)
class ProviderEndpoint:
    """One upstream vendor slot."""

    name: str  # display name (NAME env or slot name)
    host: str
    base_url: str
    api_key: str
    priority: int
    enabled: bool = True
    providers: tuple[str, ...] = ()  # empty = serves all content providers

    @property
    def vendor_group(self) -> str:
        """Normalized vendor group host to detect same-vendor slots."""
        return self.host.lower().strip()

    def serves(self, provider_name: str) -> bool:
        if not self.enabled:
            return False
        p_name = provider_name.strip().lower()
        if self.providers:
            return p_name in self.providers
        if "short-drama-pro" in self.host.lower():
            return p_name in (
                "starshort", "dramabox", "flickshort",
                "netshort", "shortmax", "reelshort_sdp",
            )
        return True


@dataclass
class _CircuitState:
    consecutive_failures: int = 0
    unhealthy_until: float = 0.0
    probing: bool = False
    rate_limited_until: float = 0.0
    last_http: int | None = None
    last_code: str | None = None
    opened: bool = False


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
    """Build the ordered upstream pool. Legacy DRAMA_API_* is the primary."""
    from ...config import settings

    def slot(
        slot_name: str, priority: int, name: str | None, host: str | None,
        base: str | None, key: str | None, providers: str | None,
    ) -> ProviderEndpoint | None:
        host = (host or "").strip()
        key = (key or "").strip()
        if not host or not key:
            return None
        base_url = (base or "").strip().rstrip("/") or f"https://{host}"
        display = (name or "").strip() or slot_name
        return ProviderEndpoint(
            name=display, host=host, base_url=base_url, api_key=key,
            priority=priority, enabled=True,
            providers=_parse_providers(providers),
        )

    endpoints: list[ProviderEndpoint] = []
    primary = slot(
        "primary", 0,
        settings.DRAMA_API_PRIMARY_NAME,
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
            getattr(settings, f"DRAMA_API_FALLBACK_{i}_NAME", None),
            getattr(settings, f"DRAMA_API_FALLBACK_{i}_HOST", None),
            getattr(settings, f"DRAMA_API_FALLBACK_{i}_BASE_URL", None),
            getattr(settings, f"DRAMA_API_FALLBACK_{i}_KEY", None),
            getattr(settings, f"DRAMA_API_FALLBACK_{i}_PROVIDERS", None),
        )
        if fb is not None:
            endpoints.append(fb)
    return sorted(endpoints, key=lambda e: e.priority)


def endpoint_status(name: str) -> str:
    """One upstream's state: healthy|degraded|cooldown|half_open|
    rate_limited|auth_error|subscription_error. Never exposes secrets."""
    state = _state_for(name)
    now = time.monotonic()
    if state.last_code == "AUTH_FAILED":
        return "auth_error"
    if state.last_code == "SUBSCRIPTION_ERROR":
        return "subscription_error"
    if state.unhealthy_until > now:
        return "cooldown"
    if state.opened:
        # Cooldown expired, awaiting the single half-open probe.
        return "half_open"
    if state.consecutive_failures > 0:
        # Flaky but below the trip threshold.
        return "degraded"
    if state.rate_limited_until > now:
        return "rate_limited"
    return "healthy"


def pool_health(endpoints: list[ProviderEndpoint] | None = None) -> dict[str, dict[str, Any]]:
    """Safe status snapshot per upstream. No keys, no URLs with secrets."""
    if endpoints is None:
        endpoints = load_pool_from_settings()
    out: dict[str, dict[str, Any]] = {}
    for ep in endpoints:
        state = _state_for(ep.name)
        out[ep.name] = {
            "status": endpoint_status(ep.name),
            "host": ep.host,
            "vendor_group": ep.vendor_group,
            "last_http": state.last_http,
            "last_error_code": state.last_code,
        }
    return out


def _record_success(name: str, http_status: int | None = None) -> None:
    state = _state_for(name)
    state.consecutive_failures = 0
    state.unhealthy_until = 0.0
    state.probing = False
    state.opened = False
    state.rate_limited_until = 0.0
    state.last_http = http_status
    state.last_code = None

def _record_failure(name: str, *, code: str | None = None,
                    http_status: int | None = None,
                    rate_limited: bool = False,
                    retry_after: float | None = None) -> None:
    state = _state_for(name)
    state.last_code = code
    state.last_http = http_status
    if rate_limited:
        wait = retry_after if retry_after and retry_after > 0 else RATE_LIMIT_COOLDOWN_SECONDS
        state.rate_limited_until = time.monotonic() + min(wait, 600.0)
        return
    state.probing = False
    state.consecutive_failures += 1
    if state.consecutive_failures >= CIRCUIT_FAILURE_THRESHOLD:
        state.unhealthy_until = time.monotonic() + CIRCUIT_COOLDOWN_SECONDS
        state.opened = True


def _is_usable(ep: ProviderEndpoint, now: float) -> tuple[bool, str]:
    """(usable, reason). Half-open upstreams admit exactly one probe."""
    state = _state_for(ep.name)
    if state.unhealthy_until > now:
        return False, "cooldown"
    if state.consecutive_failures > 0 and not state.probing:
        # First attempt after failures is the half-open probe; concurrent
        # attempts back off instead of hammering.
        state.probing = True
        return True, "half_open_probe"
    if state.probing:
        return False, "half_open_busy"
    if state.rate_limited_until > now:
        return False, "rate_limited"
    # Same credentials share one rate-limited quota pool: only pools
    # without an active backoff are eligible. Different keys on the same
    # host are independent and still tried; keys are never rotated to
    # bypass limits — a limited pool is skipped, never forced.
    if _limited_pools.get((ep.host, ep.api_key), 0.0) > now:
        return False, "rate_limited"
    return True, "ok"


class PoolExhausted(Exception):
    """All usable upstreams failed. Carries per-endpoint codes, no secrets."""

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
    """Run one adapter operation across the upstream pool.

    Returns (result, upstream_name). Scanner -> content adapter ->
    UpstreamRouter (here) -> primary -> fallbacks. See module docstring.
    """
    from . import get_provider

    endpoints = [
        ep for ep in load_pool_from_settings() if ep.serves(provider_name)
    ]
    if not endpoints and provider_name == "rapidix":
        from ...config import settings
        if settings.rapidix_configured():
            endpoints = [
                ProviderEndpoint(
                    name="rapidix",
                    host=settings.RAPIDAPI_HOST or "",
                    base_url=settings.RAPIDAPI_BASE_URL or f"https://{settings.RAPIDAPI_HOST}",
                    api_key=settings.rapidix_key(),
                    priority=99,
                    enabled=True,
                    providers=("rapidix",),
                )
            ]
    if not endpoints:
        raise PoolExhausted(
            "NOT_CONFIGURED",
            f"No upstream endpoint configured for '{provider_name}'.",
            [],
        )
    attempts: list[dict[str, str]] = []
    failed_vendor_groups: set[str] = set()

    for ep in endpoints:
        if ep.vendor_group in failed_vendor_groups:
            logger.info(
                "upstream=%s host=%s skipped (vendor_group=%s down with vendor-wide outage)",
                ep.name, ep.host, ep.vendor_group,
            )
            attempts.append({
                "endpoint": ep.name,
                "vendor_group": ep.vendor_group,
                "code": "VENDOR_DOWN",
            })
            continue

        usable, _reason = _is_usable(ep, time.monotonic())
        if not usable:
            continue
        adapter = get_provider(provider_name, transport=transport, endpoint=ep)
        try:
            result = await getattr(adapter, operation)(**kwargs)
        except Exception as exc:
            code = getattr(exc, "code", "TEMPORARY") or "TEMPORARY"
            http_status = getattr(exc, "http_status", None)

            # Vendor-wide outage (502, 503, 504): short-circuit remaining slots in this vendor group
            if http_status in (502, 503, 504):
                failed_vendor_groups.add(ep.vendor_group)

            if code in CONFIG_ERROR_CODES:
                _record_failure(ep.name, code=code, http_status=http_status)
                logger.warning(
                    "upstream=%s host=%s config error=%s; not retrying",
                    ep.name, ep.host, code,
                )
                raise PoolExhausted(
                    "CONFIG_ERROR" if code == "AUTH_FAILED" else code,
                    f"Upstream '{ep.name}' misconfigured ({code}).",
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
                _record_failure(ep.name, code=code, rate_limited=True, retry_after=wait)
                _limited_pools[(ep.host, ep.api_key)] = time.monotonic() + min(wait, 600.0)
                attempts.append({"endpoint": ep.name, "code": code})
                logger.warning(
                    "upstream=%s host=%s status=429 rate_limited; independent pools only",
                    ep.name, ep.host,
                )
                continue
            if code in ("NOT_CONFIGURED", "UNSUPPORTED", "UNSUPPORTED_PROVIDER"):
                attempts.append({"endpoint": ep.name, "code": code})
                continue
            # Failoverable: timeout / network / 5xx / invalid / temporary.
            _record_failure(ep.name, code=code, http_status=http_status)
            attempts.append({"endpoint": ep.name, "code": code})
            logger.warning(
                "upstream=%s host=%s status=%s failover_to=next",
                ep.name, ep.host, code,
            )
            continue
        _record_success(ep.name)
        if ep.name != endpoints[0].name:
            logger.info("upstream=%s host=%s recovered via failover", ep.name, ep.host)
        return result, ep.name
    raise PoolExhausted(
        "ALL_PROVIDERS_FAILED",
        f"All upstream endpoints failed for '{provider_name}'.",
        attempts,
    )
