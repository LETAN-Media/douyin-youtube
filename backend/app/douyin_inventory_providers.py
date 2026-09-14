"""Browser-based Douyin profile inventory providers.

Primary: Playwright Chromium profile scanner that intercepts real
``/aweme/v1/web/aweme/post/`` network responses. No MP4 is downloaded
during inventory scans.

Fallback (last resort): yt-dlp profile extraction.

Download pipeline (Rcuts primary -> Rcuts fallback -> yt-dlp) is NOT
changed here; see ``app.douyin``.
"""

import base64
import json
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

import yt_dlp

from app.config import settings

logger = logging.getLogger("douyin-youtube-inventory-providers")

AUTH_REQUIRED_MESSAGE = (
    "Douyin login cookies are required for profile inventory sync"
)

AWEME_POST_MARKER = "/aweme/v1/web/aweme/post/"


class DouyinInventoryError(RuntimeError):
    pass


class DouyinAuthRequiredError(DouyinInventoryError):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Cookie support (DOUYIN_COOKIES_B64 = base64 of Netscape cookies.txt)
# Never log cookie values. Never expose cookies via API.
# ---------------------------------------------------------------------------


def cookies_configured() -> bool:
    return bool((settings.douyin_cookies_b64 or "").strip())


def decode_netscape_cookies_raw() -> str:
    raw_b64 = (settings.douyin_cookies_b64 or "").strip()
    if not raw_b64:
        raise DouyinAuthRequiredError(AUTH_REQUIRED_MESSAGE)
    try:
        return base64.b64decode(raw_b64).decode("utf-8", errors="replace")
    except Exception as exc:
        raise DouyinAuthRequiredError(
            "Douyin cookies are invalid (base64 decode failed)"
        ) from exc


def parse_netscape_cookies(text: str) -> list[dict[str, Any]]:
    """Parse Netscape cookies.txt into a list of cookie dicts.

    Returns items with keys: name, value, domain, path, expires, secure.
    httpOnly cannot be reliably detected from Netscape format; callers may
    set it explicitly when known.
    """
    cookies: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            # Lenient: split on whitespace as fallback.
            parts = line.split()
            if len(parts) < 7:
                continue
        domain, _, path, secure, expires, name, value = parts[:7]
        try:
            expires_int = int(float(expires))
        except ValueError:
            expires_int = 0
        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": domain,
                "path": path or "/",
                "expires": expires_int,
                "secure": secure.upper() == "TRUE",
            }
        )
    return cookies


def netscape_to_playwright_cookies(
    parsed: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert parsed Netscape cookies to Playwright cookie dicts.

    No hard-coded cookie values. Domains are normalized so Douyin pages
    receive them (``.douyin.com``).
    """
    out: list[dict[str, Any]] = []
    for item in parsed:
        domain = str(item.get("domain") or "").strip()
        if not domain:
            continue
        # Normalize to a Douyin domain when the cookie came from a
        # Douyin host without leading dot.
        if "douyin.com" in domain and not domain.startswith("."):
            domain = "." + domain.lstrip(".") if "." not in domain[:1] else domain
            if not domain.startswith("."):
                # e.g. www.douyin.com -> .douyin.com for broad matching
                if domain.endswith("douyin.com"):
                    domain = ".douyin.com"
        cookie: dict[str, Any] = {
            "name": str(item.get("name") or ""),
            "value": str(item.get("value") or ""),
            "domain": domain,
            "path": str(item.get("path") or "/"),
            "secure": bool(item.get("secure", False)),
        }
        expires = int(item.get("expires") or 0)
        # Playwright treats -1 as session cookie; 0 would mean epoch.
        cookie["expires"] = expires if expires > 0 else -1
        if not cookie["name"]:
            continue
        out.append(cookie)
    return out


def load_playwright_cookies() -> list[dict[str, Any]]:
    text = decode_netscape_cookies_raw()
    parsed = parse_netscape_cookies(text)
    if not parsed:
        raise DouyinAuthRequiredError(
            "Douyin cookies are empty or invalid (no cookies parsed)"
        )
    return netscape_to_playwright_cookies(parsed)


def cookies_look_expired(parsed: list[dict[str, Any]]) -> bool:
    """Best-effort expiry check without network access.

    Returns True only when every cookie with an expiry is in the past.
    Session cookies (expires <= 0) are ignored for this check.
    """
    now = int(time.time())
    expirable = [c for c in parsed if int(c.get("expires") or 0) > 0]
    if not expirable:
        return False
    return all(int(c.get("expires") or 0) < now for c in expirable)


# ---------------------------------------------------------------------------
# /aweme/v1/web/aweme/post/ response parsing (real Douyin JSON)
# ---------------------------------------------------------------------------


def parse_aweme_post_response(data: Any) -> tuple[list[dict[str, Any]], int, str]:
    """Parse one ``aweme/post`` JSON payload.

    Returns (videos, has_more, max_cursor). Videos contain:
    aweme_id, desc, create_time, author, cover, share_url, duration,
    statistics plus normalized title/description/url/douyin_created_at.
    """
    if not isinstance(data, dict):
        return [], 0, ""

    aweme_list = data.get("aweme_list") or data.get("awemeList") or []
    if not isinstance(aweme_list, list):
        aweme_list = []

    try:
        has_more = int(data.get("has_more", data.get("hasMore", 0)) or 0)
    except (TypeError, ValueError):
        has_more = 0
    max_cursor = str(data.get("max_cursor", data.get("maxCursor", "")) or "")

    videos: list[dict[str, Any]] = []
    for item in aweme_list:
        if not isinstance(item, dict):
            continue
        aweme_id = str(item.get("aweme_id") or item.get("awemeId") or "").strip()
        if not aweme_id:
            continue
        desc = str(item.get("desc") or "").strip()
        author_obj = item.get("author") or {}
        author = ""
        if isinstance(author_obj, dict):
            author = str(
                author_obj.get("nickname") or author_obj.get("unique_id") or ""
            ).strip()
        cover = ""
        video_obj = item.get("video") or {}
        if isinstance(video_obj, dict):
            cover_obj = video_obj.get("cover") or {}
            if isinstance(cover_obj, dict):
                urls = cover_obj.get("url_list") or cover_obj.get("urlList") or []
                if isinstance(urls, list) and urls:
                    cover = str(urls[0])
        share_url = str(item.get("share_url") or item.get("shareUrl") or "").strip()
        duration = item.get("duration")
        try:
            duration_int = int(duration) if duration is not None else 0
        except (TypeError, ValueError):
            duration_int = 0
        statistics = item.get("statistics") if isinstance(item.get("statistics"), dict) else {}

        create_time = item.get("create_time", item.get("createTime", 0))
        douyin_created_at = None
        try:
            ts = int(create_time)
            if ts > 0:
                douyin_created_at = datetime.fromtimestamp(ts, tz=timezone.utc)
        except (TypeError, ValueError):
            douyin_created_at = None

        url = share_url or f"https://www.douyin.com/video/{aweme_id}"
        title = desc[:200] if desc else aweme_id

        videos.append(
            {
                "video_id": aweme_id,
                "aweme_id": aweme_id,
                "title": title,
                "description": desc[:1000],
                "url": url,
                "douyin_created_at": douyin_created_at,
                "author": author,
                "cover": cover,
                "share_url": share_url,
                "duration": duration_int,
                "statistics": statistics,
                "create_time": create_time,
            }
        )

    return videos, has_more, max_cursor


# ---------------------------------------------------------------------------
# Provider architecture
# ---------------------------------------------------------------------------


class DouyinInventoryProvider(ABC):
    name = "base"

    @abstractmethod
    def fetch_all(
        self,
        profile_url: str,
        sec_uid: str,
        source_id: str,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    def fetch_latest(
        self,
        profile_url: str,
        sec_uid: str,
        source_id: str,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        return self.fetch_all(profile_url, sec_uid, source_id)[:limit]


class YtDlpDouyinInventoryProvider(DouyinInventoryProvider):
    """Last fallback only. Known limitation: yt-dlp cannot enumerate
    Douyin user profiles (Unsupported URL) and /video/ needs cookies."""

    name = "yt_dlp"

    def fetch_all(
        self,
        profile_url: str,
        sec_uid: str,
        source_id: str,
    ) -> list[dict[str, Any]]:
        from app.inventory import fetch_all_videos_from_source as legacy_fetch

        return legacy_fetch(profile_url, source_id)


DOUYIN_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


class PlaywrightDouyinInventoryProvider(DouyinInventoryProvider):
    """Primary provider: headless Chromium + real aweme/post interception."""

    name = "playwright"

    def __init__(self, headless: bool = True, timeout_ms: int = 45000) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms

    def _require_cookies(self) -> list[dict[str, Any]]:
        if not cookies_configured():
            raise DouyinAuthRequiredError(AUTH_REQUIRED_MESSAGE)
        return load_playwright_cookies()

    def fetch_all(
        self,
        profile_url: str,
        sec_uid: str,
        source_id: str,
    ) -> list[dict[str, Any]]:
        return self._scan(sec_uid or profile_url, full=True)

    def fetch_latest(
        self,
        profile_url: str,
        sec_uid: str,
        source_id: str,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        videos = self._scan(sec_uid or profile_url, full=False)
        return videos[:limit]

    # -- core scan (blocking; callers must run it in a thread) ------------
    def _scan(self, sec_uid_or_url: str, full: bool) -> list[dict[str, Any]]:
        cookies = self._require_cookies()

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise DouyinInventoryError(
                "Playwright is not installed on this backend (pip install playwright)"
            ) from exc

        sec_uid = self._resolve_sec_uid(sec_uid_or_url)
        target = f"https://www.douyin.com/user/{sec_uid}" if sec_uid else sec_uid_or_url

        max_pages = int(getattr(settings, "max_inventory_pages", 200) or 200)
        if not full:
            max_pages = min(max_pages, 5)

        collected: dict[str, dict[str, Any]] = {}
        seen_cursors: set[str] = set()
        last_new_count = 0
        no_progress_rounds = 0

        browser = None
        context = None
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=self.headless,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
                context = browser.new_context(
                    user_agent=DOUYIN_USER_AGENT,
                    locale="zh-CN",
                    viewport={"width": 1366, "height": 900},
                )
                if cookies:
                    try:
                        context.add_cookies(cookies)
                    except Exception as exc:
                        raise DouyinInventoryError(
                            f"Failed to apply Douyin cookies: {exc}"
                        ) from exc

                page = context.new_page()
                responses: list[Any] = []

                def _on_response(response: Any) -> None:
                    try:
                        url = response.url or ""
                    except Exception:
                        return
                    if AWEME_POST_MARKER in url:
                        responses.append(response)

                page.on("response", _on_response)
                page.goto(target, wait_until="domcontentloaded", timeout=self.timeout_ms)
                page.wait_for_timeout(4000)

                # Detect hard blocks/challenges without inventing data.
                try:
                    content = page.content()
                except Exception:
                    content = ""
                lowered = content.lower()
                if "verify" in lowered and ("slider" in lowered or "captcha" in lowered or "验证" in content):
                    raise DouyinInventoryError(
                        "Douyin challenge/captcha detected during profile scan"
                    )

                for _ in range(max_pages):
                    # Drain intercepted aweme/post responses.
                    while responses:
                        response = responses.pop(0)
                        try:
                            payload = response.json()
                        except Exception:
                            continue
                        videos, has_more, max_cursor = parse_aweme_post_response(payload)
                        for video in videos:
                            collected.setdefault(video["video_id"], video)
                        if max_cursor:
                            if max_cursor in seen_cursors:
                                pass
                            seen_cursors.add(max_cursor)
                        if not full and len(collected) >= 30:
                            break
                        if has_more == 0 and not full:
                            break

                    current_total = len(collected)
                    if current_total > last_new_count:
                        last_new_count = current_total
                        no_progress_rounds = 0
                    else:
                        no_progress_rounds += 1

                    if not full and current_total >= 30:
                        break
                    # Full mode stops only on repeated no-progress; the
                    # has_more==0 signal arrives inside payloads above and
                    # is reflected by no new IDs across scrolls.
                    if no_progress_rounds >= 4:
                        break

                    # Scroll to trigger load-more pagination.
                    try:
                        page.evaluate(
                            "window.scrollTo(0, document.body.scrollHeight)"
                        )
                    except Exception:
                        break
                    page.wait_for_timeout(2500)

                # Final drain.
                while responses:
                    response = responses.pop(0)
                    try:
                        payload = response.json()
                    except Exception:
                        continue
                    videos, _, _ = parse_aweme_post_response(payload)
                    for video in videos:
                        collected.setdefault(video["video_id"], video)

                try:
                    page.close()
                except Exception:
                    pass
        finally:
            try:
                if context is not None:
                    context.close()
            except Exception:
                pass
            try:
                if browser is not None:
                    browser.close()
            except Exception:
                pass

        ordered = list(collected.values())
        # Newest first when create_time is available.
        try:
            ordered.sort(key=lambda v: int(v.get("create_time") or 0), reverse=True)
        except Exception:
            pass
        logger.info(
            "Playwright scan collected %s unique videos (full=%s)",
            len(ordered),
            full,
        )
        return ordered

    @staticmethod
    def _resolve_sec_uid(value: str) -> str:
        text = (value or "").strip()
        if not text:
            return ""
        # Accept either a raw sec_uid or a full profile URL.
        if text.startswith("http"):
            try:
                from app.douyin_url import parse_douyin_profile_url

                parsed = parse_douyin_profile_url(text)
                if parsed is not None:
                    return parsed.sec_uid
            except Exception:
                pass
            # Fallback: last path segment.
            cleaned = text.rstrip("/").split("?")[0]
            candidate = cleaned.rsplit("/", 1)[-1]
            return candidate
        return text


def get_primary_provider() -> DouyinInventoryProvider:
    return PlaywrightDouyinInventoryProvider()


def get_fallback_provider() -> DouyinInventoryProvider:
    return YtDlpDouyinInventoryProvider()


def discover_profile_videos(
    profile_url: str,
    sec_uid: str,
    source_id: str,
    full: bool = True,
) -> tuple[list[dict[str, Any]], str]:
    """Run primary provider, then LAST fallback.

    Returns (videos, provider_name). Auth-required is never silently
    converted to an empty completed result by the caller.
    """
    primary = get_primary_provider()
    try:
        if full:
            videos = primary.fetch_all(profile_url, sec_uid, source_id)
        else:
            videos = primary.fetch_latest(profile_url, sec_uid, source_id)
        return videos, primary.name
    except DouyinAuthRequiredError:
        raise
    except DouyinInventoryError as exc:
        logger.warning("Primary inventory provider failed: %s", exc)
    except Exception:
        logger.exception("Primary inventory provider crashed")

    fallback = get_fallback_provider()
    try:
        if full:
            videos = fallback.fetch_all(profile_url, sec_uid, source_id)
        else:
            videos = fallback.fetch_latest(profile_url, sec_uid, source_id)
        return videos, fallback.name
    except Exception:
        logger.exception("Fallback inventory provider crashed")
        return [], fallback.name
