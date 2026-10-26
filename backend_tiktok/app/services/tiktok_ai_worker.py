"""AI metadata worker — polls reels claiming and generates metadata."""

import asyncio
import hashlib
import logging
import time

from ..config import settings
from ..db.repositories import ai_metadata, reels
from .ai_rate_limit import ToolNetRateLimiter
from .tiktok_ai_metadata import generate_ai_metadata

logger = logging.getLogger("backend-tiktok.services.ai_worker")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


async def ai_worker_loop(stop_event: asyncio.Event) -> None:
    if not settings.toolnet_ai_enabled:
        logger.info("AI worker disabled (TOOLNET_AI_ENABLED=false)")
        return

    logger.info("TikTok AI metadata worker started")
    rate_limiter = ToolNetRateLimiter(
        requests_per_minute=settings.toolnet_max_requests_per_minute,
        tokens_per_minute=settings.toolnet_max_tokens_per_minute,
    )
    poll_interval = max(settings.tiktok_scheduler_poll_seconds, 5)

    while not stop_event.is_set():
        try:
            await _process_batch(rate_limiter)
        except Exception as exc:
            logger.exception("ai_worker error: %s", exc)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
            break
        except asyncio.TimeoutError:
            continue

    logger.info("TikTok AI metadata worker stopped")


async def _process_batch(rate_limiter: ToolNetRateLimiter) -> None:
    batch = await ai_metadata.list_stale_for_retry(limit=10)
    if not batch:
        # Also check ready items
        batch = await ai_metadata.list_ready_for_claim(limit=10)

    for entry in batch:
        reel_db_id = entry["reel_db_id"]
        reel = await reels.get_reel(reel_db_id)
        if reel is None:
            continue

        claimed = await ai_metadata.mark_claimed(reel_db_id, settings.toolnet_model)
        if not claimed:
            continue

        source_hash = hashlib.sha256(
            (reel.get("caption") or "").encode()
        ).hexdigest()[:32]

        if entry.get("config_hash") and entry.get("config_hash") != _config_hash(reel):
            # Stale config, retry
            await ai_metadata.mark_failed(
                reel_db_id, "config_changed", retry_at=_future_iso(5)
            )
            continue

        await rate_limiter.acquire()
        try:
            result = await generate_ai_metadata(
                settings.toolnet_model, reel, reel.get("caption")
            )
            await ai_metadata.mark_success(
                reel_db_id,
                result["title"],
                result["description"],
                json.loads(result["hashtags_json"]) if result["hashtags_json"] else [],
                settings.toolnet_model,
                _config_hash(reel),
            )
        except Exception as exc:
            await ai_metadata.mark_failed(reel_db_id, str(exc), retry_at=_future_iso(10))
            logger.warning("AI metadata failed for %s: %s", reel_db_id, exc)


def _config_hash(reel: dict) -> str:
    cfg_str = f"{settings.toolnet_model}|{reel.get('caption', '')[:100]}"
    return hashlib.sha256(cfg_str.encode()).hexdigest()[:16]


def _future_iso(minutes: int) -> str:
    return time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + minutes * 60)
    )
