"""AI metadata generation via ToolNet — reusable from backend_facebook."""

import json
import logging
from typing import Any

from ..config import settings
from ..db.repositories import ai_metadata, ai_settings

logger = logging.getLogger("backend-tiktok.services.ai_metadata")


async def generate_ai_metadata(
    ai_model: str | None,
    reel: dict[str, Any],
    original_caption: str | None = None,
) -> dict[str, Any]:
    """Generate YouTube-optimized title, description, hashtags for a reel."""
    if not settings.toolnet_ai_enabled:
        logger.info("AI metadata generation disabled")
        return {"title": None, "description": None, "hashtags_json": None, "model": None}

    cfg = await ai_settings.get_ai_settings(reel.get("source_id"))
    # We don't have pipeline_id directly from reel, so pass through defaults
    system_prompt = (cfg or {}).get("system_prompt") if cfg else None
    model = ai_model or settings.toolnet_model

    caption = original_caption or (reel or {}).get("caption") or ""
    thumbnail_desc = (reel or {}).get("thumbnail_url") or ""

    prompt = _build_prompt(caption, thumbnail_desc)
    system = system_prompt or (
        "Bạn là một chuyên gia nội dung YouTube. Tạo tiêu đề, mô tả và hashtag "
        "hấp dẫn cho video TikTok, tối ưu SEO. Trả về JSON."
    )

    result = await _call_toolnet(prompt, system, model)
    return {
        "title": result.get("title"),
        "description": result.get("description"),
        "hashtags_json": json.dumps(result.get("hashtags", [])),
        "model": model,
    }


def _build_prompt(caption: str, thumbnail_hint: str) -> str:
    lines = [
        "Tạo tiêu đề, mô tả và hashtag cho video TikTok sau:",
        f"Nội dung gồng: {caption[:500] if caption else '(không có)'}",
        f"Ảnh thumbnail: {thumbnail_hint or '(không có)'}",
        "Trả về JSON với các trường: title (dài 60-100 ký tự), description (2-3 đoạn ngắn gọn), hashtags (mảng string).",
    ]
    return "\n".join(lines)


async def _call_toolnet(prompt: str, system: str, model: str) -> dict[str, Any]:
    import asyncio

    if not settings.toolnet_base_url or not settings.toolnet_api_key:
        raise RuntimeError("ToolNet not configured (TOOLNET_BASE_URL / AI_TOOLNET_URL)")

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, _call_toolnet_sync, prompt, system, model
    )


def _call_toolnet_sync(prompt: str, system: str, model: str) -> dict[str, Any]:
    import httpx

    api_key = settings.toolnet_api_key
    resp = httpx.post(
        f"{settings.toolnet_base_url.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 2000,
        },
        timeout=settings.toolnet_timeout,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"ToolNet API error: {resp.status_code}")
    data = resp.json()
    text = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
    # Strip markdown code fences if present
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"title": None, "description": text, "hashtags": []}
