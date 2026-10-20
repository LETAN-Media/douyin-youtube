"""Ordered RapidAPI provider pool with per-provider failover.

Each provider is an explicit config + adapter. The pool never guesses an
endpoint, never shares credentials, and never retries a terminal 429/auth
failure on the same provider. A scan session sticks to the provider that
answered so pagination stays valid; if it must switch, the cursor is reset and
the inventory deduplicates by Douyin video ID.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from app import douyin_quota
from app.integrations.rapidapi import adapters
from app.integrations.rapidapi.errors import RapidApiFailure, RapidApiPoolError
from app.integrations.rapidapi.provider_config import (
    RapidApiProviderConfig,
    build_provider_configs,
)

logger = logging.getLogger("rapidapi-provider-pool")

QuotaCheck = Callable[[RapidApiProviderConfig], bool]
Fetcher = Callable[[RapidApiProviderConfig, str, str | None], dict[str, Any]]


def _default_quota_check(config: RapidApiProviderConfig) -> bool:
    try:
        return douyin_quota.can_spend(
            1,
            provider_id=config.provider_id,
            default_limit=config.monthly_request_limit or None,
        )
    except Exception:
        return False


class RapidApiProviderPool:
    def __init__(
        self,
        configs: list[RapidApiProviderConfig],
        *,
        fetcher: Fetcher | None = None,
        quota_check: QuotaCheck | None = None,
    ) -> None:
        self.configs = sorted(configs, key=lambda c: (c.priority, c.provider_id))
        self._fetcher = fetcher or adapters.fetch_page
        self._quota_check = quota_check or _default_quota_check
        self._lock = threading.Lock()
        self._cooldowns: dict[str, tuple[float, str]] = {}
        self._failures: dict[str, int] = {}
        self._last_errors: dict[str, str] = {}

    # ---- public status -------------------------------------------------
    def default_provider_id(self) -> str:
        for cfg in self.configs:
            if cfg.configured:
                return cfg.provider_id
        return self.configs[0].provider_id if self.configs else "rapidapi_justone"

    def get(self, provider_id: str | None) -> RapidApiProviderConfig | None:
        if not provider_id:
            return None
        # Backward-compatible alias for sources saved before the pool existed.
        if provider_id == "rapidapi_justone":
            for cfg in self.configs:
                if cfg.provider_id in ("rapidapi_justone", "rapidapi_primary"):
                    return cfg
        for cfg in self.configs:
            if cfg.provider_id == provider_id:
                return cfg
        return None

    def configured_configs(self) -> list[RapidApiProviderConfig]:
        return [c for c in self.configs if c.configured]

    def is_supported(self, config: RapidApiProviderConfig) -> bool:
        return config.schema in adapters.ADAPTERS

    def cooldown_remaining(self, config: RapidApiProviderConfig) -> float:
        entry = self._cooldowns.get(config.provider_id)
        if entry is None:
            return 0.0
        until, _reason = entry
        return max(0.0, until - time.time())

    def is_available(self, config: RapidApiProviderConfig) -> bool:
        if not config.configured or not self.is_supported(config):
            return False
        if self.cooldown_remaining(config) > 0:
            return False
        try:
            return bool(self._quota_check(config))
        except Exception:
            return False

    def has_available_provider(self) -> bool:
        return any(self.is_available(cfg) for cfg in self.configs)

    def _provider_status(self, cfg: RapidApiProviderConfig) -> dict[str, Any]:
        try:
            quota = douyin_quota.snapshot(
                cfg.provider_id,
                default_limit=cfg.monthly_request_limit or None,
            )
        except Exception:
            quota = {
                "limit": 0,
                "remaining": 0,
                "used": 0,
                "status": "unknown",
                "exhausted": False,
            }
        public = cfg.public()
        public.update(
            {
                "schema_supported": self.is_supported(cfg),
                "available": self.is_available(cfg),
                "cooldown_seconds": round(self.cooldown_remaining(cfg), 1),
                "consecutive_failures": int(self._failures.get(cfg.provider_id, 0)),
                "last_error": self._last_errors.get(cfg.provider_id),
                "quota": quota,
            }
        )
        return public

    def quota_status(self) -> dict[str, Any]:
        """Aggregate pool capacity plus per-provider quota (no secrets)."""
        providers = [self._provider_status(cfg) for cfg in self.configs]
        configured = [p for p in providers if p["configured"]]
        if not configured:
            return {
                "provider": None,
                "required": True,
                "limit": 0,
                "remaining": 0,
                "used": 0,
                "month": douyin_quota.month_key(),
                "reset_at": None,
                "status": "quota_exhausted",
                "exhausted": True,
                "safety_margin": douyin_quota.safety_margin(),
                "source": "pool",
                "last_error": "No RapidAPI provider configured",
                "updated_at": None,
                "providers": providers,
                "configured": False,
                "config_error": "No RapidAPI provider configured",
            }

        limit = sum(int(p["quota"].get("limit") or 0) for p in configured)
        remaining = sum(int(p["quota"].get("remaining") or 0) for p in configured)
        used = sum(int(p["quota"].get("used") or 0) for p in configured)
        available = [p for p in configured if p["available"]]
        any_exhausted = all(bool(p["quota"].get("exhausted")) for p in configured)
        first = available[0] if available else configured[0]
        last_error = next(
            (p["last_error"] for p in configured if p.get("last_error")),
            None,
        )
        return {
            "provider": first["provider_id"],
            "required": True,
            "limit": limit,
            "remaining": remaining,
            "used": used,
            "month": configured[0]["quota"].get("month") or douyin_quota.month_key(),
            "reset_at": configured[0]["quota"].get("reset_at"),
            "status": (
                "quota_exhausted"
                if not available and any_exhausted
                else ("low" if not available else "ok")
            ),
            "exhausted": not available and any_exhausted,
            "safety_margin": douyin_quota.safety_margin(),
            "source": "pool",
            "last_error": last_error,
            "updated_at": configured[0]["quota"].get("updated_at"),
            "providers": providers,
            "configured": True,
            "config_error": None,
        }

    # ---- scan lifecycle ------------------------------------------------
    def open_session(
        self,
        sec_uid: str,
        *,
        preferred_provider_id: str | None = None,
    ) -> "RapidApiScanSession":
        return RapidApiScanSession(self, sec_uid, preferred_provider_id)

    def record_success(self, config: RapidApiProviderConfig) -> None:
        with self._lock:
            self._failures.pop(config.provider_id, None)
            self._cooldowns.pop(config.provider_id, None)
            self._last_errors.pop(config.provider_id, None)

    def record_failure(
        self,
        config: RapidApiProviderConfig,
        failure: RapidApiFailure,
    ) -> None:
        kind = failure.kind or "provider"
        with self._lock:
            count = int(self._failures.get(config.provider_id, 0)) + 1
            self._failures[config.provider_id] = count
            base = {
                "quota": 3600.0,
                "auth": 1800.0,
                "rate_limit": 120.0,
                "timeout": 60.0,
                "unavailable": 60.0,
                "schema": 300.0,
            }.get(kind, 60.0)
            if kind not in ("quota", "auth"):
                base = min(base * (2 ** min(count - 1, 4)), 1800.0)
            self._cooldowns[config.provider_id] = (
                time.time() + base,
                kind,
            )
            self._last_errors[config.provider_id] = str(failure)[:500]

        logger.warning(
            "RapidAPI provider %s failed (%s); cooldown %.0fs: %s",
            config.provider_id,
            kind,
            base,
            str(failure)[:300],
        )


class RapidApiScanSession:
    """Sticky provider pagination with cursor-safe fallback."""

    def __init__(
        self,
        pool: RapidApiProviderPool,
        sec_uid: str,
        preferred_provider_id: str | None = None,
    ) -> None:
        self.pool = pool
        self.sec_uid = sec_uid
        self.failures: list[RapidApiFailure] = []
        self.provider_id: str | None = None

        order = list(pool.configs)
        preferred = pool.get(preferred_provider_id)
        if preferred is not None and preferred in order:
            start = order.index(preferred)
            order = order[start:] + order[:start]
        self._order = order
        self._index = 0

    def _current(self) -> RapidApiProviderConfig | None:
        if self._index >= len(self._order):
            return None
        return self._order[self._index]

    def fetch_page(self, cursor: str | None = None) -> dict[str, Any]:
        selected_cursor = cursor
        while True:
            config = self._current()
            if config is None:
                raise RapidApiPoolError(self.failures)

            if not self.pool.is_available(config):
                # If we are skipping before any successful page, the caller's
                # cursor belongs to another provider and must not be reused.
                selected_cursor = None
                self._index += 1
                continue

            try:
                page = self.pool._fetcher(config, self.sec_uid, selected_cursor)
            except RapidApiFailure as failure:
                if not failure.provider_id:
                    failure.provider_id = config.provider_id
                self.failures.append(failure)
                self.pool.record_failure(config, failure)
                if failure.kind == "invalid_request":
                    raise RapidApiPoolError([failure]) from failure
                selected_cursor = None
                self._index += 1
                continue
            except Exception as exc:  # adapter bugs must not kill the scan
                failure = RapidApiFailure(
                    f"{type(exc).__name__}: {exc}",
                    kind="provider",
                    provider_id=config.provider_id,
                )
                self.failures.append(failure)
                self.pool.record_failure(config, failure)
                selected_cursor = None
                self._index += 1
                continue

            self.pool.record_success(config)
            self.provider_id = config.provider_id
            page["provider_id"] = config.provider_id
            page["provider_name"] = config.name
            page["provider_switched"] = bool(self.failures)
            return page


_pool: RapidApiProviderPool | None = None
_pool_lock = threading.Lock()


def get_rapidapi_pool() -> RapidApiProviderPool:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = RapidApiProviderPool(build_provider_configs())
        return _pool


def reset_rapidapi_pool_for_tests(
    pool: RapidApiProviderPool | None = None,
) -> None:
    global _pool
    with _pool_lock:
        _pool = pool


__all__ = [
    "RapidApiProviderPool",
    "RapidApiScanSession",
    "get_rapidapi_pool",
    "reset_rapidapi_pool_for_tests",
]
