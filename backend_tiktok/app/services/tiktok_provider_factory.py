"""Provider factory — Scheduler depends on this, never on concrete providers.

The factory reads ``TIKTOK_PROVIDER`` and instantiates the correct adapter.
Adding a new provider means registering it here; the Scheduler is untouched.
"""

import logging

from ..config import settings
from .tiktok_provider import TikTokProvider
from .tiktok_source_api import TikTokSourceAPIProvider

logger = logging.getLogger("backend-tiktok.providers.factory")

_PROVIDERS: dict[str, type[TikTokProvider]] = {
    "source_api": TikTokSourceAPIProvider,
}


def get_scan_provider() -> TikTokProvider:
    """Return the configured scan/list provider for the auto pipeline."""
    name = (settings.tiktok_provider or "source_api").strip().lower()
    cls = _PROVIDERS.get(name)
    if cls is None:
        logger.warning("Unknown TIKTOK_PROVIDER '%s', falling back to source_api", name)
        cls = TikTokSourceAPIProvider
    return cls()


def register_provider(name: str, cls: type[TikTokProvider]) -> None:
    _PROVIDERS[name] = cls


def available_providers() -> list[str]:
    return list(_PROVIDERS.keys())
