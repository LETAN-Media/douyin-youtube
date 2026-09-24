"""Provider registry for pipeline sources (Douyin/Facebook/...)."""

import logging
from abc import ABC, abstractmethod
from typing import Any

from app.models import PlatformAccount

logger = logging.getLogger("douyin-youtube-providers")


class SourceProvider(ABC):
    platform: str = "base"

    @abstractmethod
    def test_account(self, account: PlatformAccount) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def resolve_source(self, url: str) -> dict[str, Any]:
        """Parse URL into {platform, source_external_id, source_url, source_name}."""
        raise NotImplementedError

    @abstractmethod
    def scan_source(self, account: PlatformAccount | None, source: Any) -> list[dict[str, Any]]:
        """Return list of videos for a source (uses global account if needed)."""
        raise NotImplementedError


class DouyinProvider(SourceProvider):
    platform = "douyin"

    def test_account(self, account: PlatformAccount) -> dict[str, Any]:
        from app.platform_accounts import test_platform_account
        from app.db import SessionLocal
        with SessionLocal() as db:
            return test_platform_account(db, "douyin")

    def resolve_source(self, url: str) -> dict[str, Any]:
        from app.douyin import parse_profile_url
        parsed = parse_profile_url(url)
        sec_uid = parsed.get("sec_uid") if parsed else None
        clean = parsed.get("clean_url") if parsed else url
        return {
            "platform": "douyin",
            "source_external_id": sec_uid,
            "source_url": clean or url,
            "source_name": None,
        }

    def scan_source(self, account: PlatformAccount | None, source: Any) -> list[dict[str, Any]]:
        # source is DouyinSource or PipelineSource with profile_url/sec_uid
        profile_url = getattr(source, "profile_url", None) or getattr(source, "source_url", None) or ""
        sec_uid = getattr(source, "douyin_sec_uid", None) or getattr(source, "source_external_id", None) or ""
        if sec_uid and not profile_url:
            profile_url = f"https://www.douyin.com/user/{sec_uid}"
        from app.douyin_inventory_providers import discover_profile_videos
        from app.platform_accounts import load_platform_cookie_jar
        jar = None
        if account and account.credentials_encrypted:
            jar = load_platform_cookie_jar("douyin")
        # Also fallback to per-source cookie if present (for migration period)
        if not jar:
            try:
                from app.source_cookies import load_source_cookie_jar
                if hasattr(source, "cookie_encrypted") and source.cookie_encrypted:
                    jar = load_source_cookie_jar(source)  # type: ignore
            except Exception:
                jar = None
        videos, _ = discover_profile_videos(profile_url, sec_uid, getattr(source, "id", "unknown"), full=False, cookie_jar=jar)
        return videos


class FacebookProvider(SourceProvider):
    platform = "facebook"

    def test_account(self, account: PlatformAccount) -> dict[str, Any]:
        # Stub: report not connected until real Facebook auth is implemented
        return {"ok": False, "platform": "facebook", "error": "Facebook provider not yet configured (stub)"}

    def resolve_source(self, url: str) -> dict[str, Any]:
        # Basic parse for Facebook Page/Profile URL
        return {
            "platform": "facebook",
            "source_external_id": url.split("/")[-1].split("?")[0],
            "source_url": url,
            "source_name": None,
        }

    def scan_source(self, account: PlatformAccount | None, source: Any) -> list[dict[str, Any]]:
        logger.warning("Facebook scan requested but provider is stub")
        return []


class SourceProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, SourceProvider] = {}
        self.register(DouyinProvider())
        self.register(FacebookProvider())

    def register(self, provider: SourceProvider) -> None:
        self._providers[provider.platform] = provider

    def get(self, platform: str) -> SourceProvider | None:
        return self._providers.get(platform)

    def platforms(self) -> list[str]:
        return list(self._providers.keys())


registry = SourceProviderRegistry()
