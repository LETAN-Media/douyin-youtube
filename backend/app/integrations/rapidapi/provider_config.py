"""Configuration and public metadata for RapidAPI Douyin providers.

No API key is ever included in ``public()``. Providers are configured from
explicit, documented fields; an incomplete slot is reported and skipped rather
than guessed.

Fallback slots are dynamic: ``DOUYIN_RAPIDAPI_FALLBACK_1_*``,
``DOUYIN_RAPIDAPI_FALLBACK_2_*``, ``DOUYIN_RAPIDAPI_FALLBACK_3_*``, ... are
discovered from ENV (and backend/.env for local development). A slot with an
empty HOST or KEY is never activated.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from app.config import settings

DEFAULT_PATHS: dict[str, str] = {
    "justone_v3": "/api/douyin/get-user-video-list/v3",
}

_SLOT_RE = re.compile(r"^DOUYIN_RAPIDAPI_FALLBACK_(\d+)_(.+)$")
_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


@dataclass(frozen=True)
class RapidApiProviderConfig:
    provider_id: str
    name: str
    api_key: str
    host: str
    base_url: str
    path: str
    schema: str
    priority: int
    enabled: bool = True
    timeout_seconds: float = 30.0
    max_retries: int = 1
    monthly_request_limit: int = 0
    config_error: str | None = None

    @property
    def configured(self) -> bool:
        return bool(
            self.enabled
            and not self.config_error
            and self.api_key
            and self.host
            and self.base_url
            and self.path
            and self.schema
        )

    def public(self) -> dict[str, Any]:
        """Safe status payload. Never includes credentials."""
        return {
            "provider_id": self.provider_id,
            "name": self.name,
            "host": self.host,
            "base_url": self.base_url,
            "path": self.path,
            "schema": self.schema,
            "priority": self.priority,
            "enabled": self.enabled,
            "configured": self.configured,
            "key_configured": bool(self.api_key),
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "monthly_request_limit": self.monthly_request_limit,
            "config_error": self.config_error,
        }


def _env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    if _ENV_FILE.exists():
        try:
            values.update(
                {
                    str(k): str(v)
                    for k, v in dotenv_values(_ENV_FILE).items()
                    if v is not None
                }
            )
        except Exception:
            pass
    values.update({str(k): str(v) for k, v in os.environ.items()})
    return values


def _base_url(host: str, base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if base:
        return base
    host = (host or "").strip()
    return f"https://{host}" if host else ""


def _primary_config() -> RapidApiProviderConfig:
    legacy_key = (settings.rapidapi_key or "").strip()
    legacy_host = (settings.douyin_rapidapi_host or "").strip()
    legacy_base = (settings.douyin_rapidapi_base_url or "").strip()
    legacy_path = (settings.douyin_rapidapi_user_posts_path or "").strip()

    key = (settings.douyin_rapidapi_primary_key or "").strip() or legacy_key
    host = (settings.douyin_rapidapi_primary_host or "").strip() or legacy_host
    base = (
        (settings.douyin_rapidapi_primary_base_url or "").strip()
        or legacy_base
    )
    base = _base_url(host, base)
    schema = (settings.douyin_rapidapi_primary_schema or "").strip() or "justone_v3"
    path = (settings.douyin_rapidapi_primary_user_posts_path or "").strip()
    path = path or legacy_path or DEFAULT_PATHS.get(schema, "")

    legacy_mode = not (
        (settings.douyin_rapidapi_primary_key or "").strip()
        or (settings.douyin_rapidapi_primary_host or "").strip()
        or (settings.douyin_rapidapi_primary_base_url or "").strip()
        or (settings.douyin_rapidapi_primary_user_posts_path or "").strip()
    )
    provider_id = "rapidapi_justone" if legacy_mode else "rapidapi_primary"
    name = (
        (settings.douyin_rapidapi_primary_name or "").strip()
        or ("RapidAPI JustOne" if legacy_mode else "RapidAPI Primary")
    )

    missing = []
    if not key:
        missing.append("DOUYIN_RAPIDAPI_PRIMARY_KEY (or RAPIDAPI_KEY)")
    if not host:
        missing.append("DOUYIN_RAPIDAPI_PRIMARY_HOST (or DOUYIN_RAPIDAPI_HOST)")
    if not path:
        missing.append("DOUYIN_RAPIDAPI_PRIMARY_USER_POSTS_PATH")
    if not schema:
        missing.append("DOUYIN_RAPIDAPI_PRIMARY_SCHEMA")
    return RapidApiProviderConfig(
        provider_id=provider_id,
        name=name,
        api_key=key,
        host=host,
        base_url=base,
        path=path,
        schema=schema,
        priority=0,
        enabled=True,
        timeout_seconds=float(
            settings.douyin_rapidapi_primary_timeout_seconds
            or settings.douyin_rapidapi_timeout_seconds
            or 30
        ),
        max_retries=max(
            0,
            int(
                settings.douyin_rapidapi_primary_max_retries
                if settings.douyin_rapidapi_primary_max_retries is not None
                else settings.douyin_rapidapi_max_retries
            ),
        ),
        monthly_request_limit=max(
            0,
            int(
                settings.douyin_rapidapi_primary_monthly_request_limit
                or settings.rapidapi_monthly_request_limit
                or 0
            ),
        ),
        config_error=(
            "Missing " + ", ".join(missing) if missing else None
        ),
    )


def _slot_values(env: dict[str, str], slot: int) -> dict[str, str]:
    prefix = f"DOUYIN_RAPIDAPI_FALLBACK_{slot}_"
    return {
        key[len(prefix):]: value
        for key, value in env.items()
        if key.startswith(prefix)
    }


def _fallback_config(env: dict[str, str], slot: int) -> RapidApiProviderConfig | None:
    values = _slot_values(env, slot)
    if not values:
        return None
    host = (values.get("HOST") or "").strip()
    key = (values.get("KEY") or "").strip()
    if not key:
        # Explicit slot key first; never copy the primary key.
        key = (env.get(f"RAPIDAPI_KEY_{slot}") or "").strip()
    base = _base_url(host, values.get("BASE_URL", ""))
    schema = (values.get("TYPE") or values.get("SCHEMA") or "").strip()
    path = (
        values.get("USER_POSTS_PATH")
        or values.get("PATH")
        or DEFAULT_PATHS.get(schema, "")
    ).strip()
    enabled = (values.get("ENABLED", "true") or "").strip().lower() not in (
        "0", "false", "no", "off"
    )
    config_error = None
    missing = []
    if not host:
        missing.append("HOST")
    if not key:
        missing.append("KEY")
    if not schema:
        missing.append("TYPE/SCHEMA")
    if not path:
        missing.append("PATH")
    if missing:
        config_error = (
            f"Missing {', '.join(f'DOUYIN_RAPIDAPI_FALLBACK_{slot}_{m}' for m in missing)}"
        )
    return RapidApiProviderConfig(
        provider_id=f"rapidapi_fallback_{slot}",
        name=(values.get("NAME") or f"RapidAPI Fallback {slot}").strip(),
        api_key=key,
        host=host,
        base_url=base,
        path=path,
        schema=schema,
        priority=int(values.get("PRIORITY") or slot),
        enabled=enabled,
        timeout_seconds=float(values.get("TIMEOUT_SECONDS") or 30),
        max_retries=max(0, int(values.get("MAX_RETRIES") or 1)),
        monthly_request_limit=max(
            0,
            int(
                values.get("MONTHLY_REQUEST_LIMIT")
                or settings.rapidapi_monthly_request_limit
                or 0
            ),
        ),
        config_error=config_error,
    )


def build_provider_configs() -> list[RapidApiProviderConfig]:
    """Return primary + every configured fallback slot, ordered by priority."""
    env = _env_values()
    slots = sorted(
        {
            int(match.group(1))
            for key in env
            if (match := _SLOT_RE.match(key))
        }
    )
    configs = [_primary_config()]
    for slot in slots:
        cfg = _fallback_config(env, slot)
        if cfg is not None:
            configs.append(cfg)
    return sorted(configs, key=lambda c: (c.priority, c.provider_id))


__all__ = [
    "DEFAULT_PATHS",
    "RapidApiProviderConfig",
    "build_provider_configs",
]
