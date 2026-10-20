"""Schema adapters for RapidAPI providers.

Each adapter is opt-in by an explicit ``schema`` name in ENV. New RapidAPI
products are added here only after reading their real documentation; there is
no generic "guess the response" path.
"""

from __future__ import annotations

from typing import Any, Callable

from app.integrations.rapidapi.errors import RapidApiFailure
from app.integrations.rapidapi.provider_config import RapidApiProviderConfig

Adapter = Callable[[RapidApiProviderConfig, str, str | None], dict[str, Any]]


def _justone_v3(
    config: RapidApiProviderConfig,
    sec_uid: str,
    cursor: str | None,
) -> dict[str, Any]:
    from app.integrations.rapidapi import justone

    try:
        return justone.fetch_page(config, sec_uid, cursor)
    except justone.JustOneError as exc:
        raise RapidApiFailure(
            str(exc),
            kind=exc.kind,
            provider_id=config.provider_id,
            retryable=exc.retryable,
        ) from exc


#: Explicit schema registry. Unknown schemas fail closed and are visible in
#: provider status instead of being sent a guessed request.
ADAPTERS: dict[str, Adapter] = {
    "justone_v3": _justone_v3,
}


def fetch_page(
    config: RapidApiProviderConfig,
    sec_uid: str,
    cursor: str | None,
) -> dict[str, Any]:
    adapter = ADAPTERS.get(config.schema)
    if adapter is None:
        raise RapidApiFailure(
            f"Unsupported RapidAPI schema '{config.schema}'",
            kind="schema",
            provider_id=config.provider_id,
            retryable=False,
        )
    return adapter(config, sec_uid, cursor)


__all__ = ["ADAPTERS", "Adapter", "fetch_page"]
