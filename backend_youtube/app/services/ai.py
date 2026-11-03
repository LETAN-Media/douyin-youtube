import logging
from typing import Any
from .ai_rate_limiter import AIRateLimiter

logger = logging.getLogger("backend-youtube.ai")


class AIError(RuntimeError):
    pass


async def enrich_metadata(
    rate_limiter: AIRateLimiter,
    *,
    youtube_video_id: str,
    title: str | None,
    description: str | None,
    duration_seconds: int | None,
    view_count: int | None,
    tags: list[str] | None,
    strategy: str = "auto",
) -> dict[str, Any]:
    base, api_key, model = _toolnet_params()
    if not await rate_limiter.acquire():
        raise AIError("Rate-limited: too many ToolNet requests")
    text_content = []
    if title:
        text_content.append(title)
    if description:
        text_content.append(description[:2000])
    combined = " ".join(text_content).strip()
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a social media assistant. Given the title, description and metadata "
                    "of a YouTube video, produce a catchy caption (<=200 characters), a list of 3-8 "
                    "relevant hashtags, an engaging short title suggestion (<=100 chars), and an "
                    "improved description for cross-posting to Facebook Reels. Return JSON only."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Title: {title}\nDescription: {description}\n"
                    f"Duration seconds: {duration_seconds}\nView count: {view_count}\n"
                    f"Tags: {tags}\nStrategy: {strategy}\n"
                    "Return JSON: {caption, hashtags, title_suggestion, description_suggestion}"
                ),
            },
        ],
        "max_tokens": max(1, _ai_max_tokens(strategy)),
        "temperature": 0.7,
    }
    import httpx
    from ..config import settings
    async with httpx.AsyncClient(timeout=httpx.Timeout(settings.TOOLNET_TIMEOUT)) as client:
        resp = await client.post(
            f"{base}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        )
        if resp.status_code != 200:
            raise AIError(f"ToolNet API error {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
    content = None
    if data.get("choices"):
        content = data["choices"][0].get("message", {}).get("content")
    if not content:
        content = data.get("choices", [{}])[0].get("content", "")
    import json
    try:
        parsed = json.loads(content)
    except Exception as exc:
        raise AIError(f"Failed to parse ToolNet JSON response: {exc}") from exc
    return parsed


def _toolnet_params() -> tuple[str, str, str]:
    from ..config import settings
    if not settings.TOOLNET_AI_ENABLED:
        raise AIError("TOOLNET_AI_ENABLED is not true")
    base = (settings.TOOLNET_BASE_URL or "").strip().rstrip("/")
    api_key = (settings.TOOLNET_API_KEY or "").strip()
    model = (settings.TOOLNET_MODEL or "gpt-4o-mini").strip()
    if not base or not api_key:
        raise AIError("TOOLNET_BASE_URL and TOOLNET_API_KEY are required")
    return base, api_key, model


def _ai_max_tokens(strategy: str) -> int:
    from ..config import settings
    return settings.AI_MAX_TOKENS_PER_MINUTE if strategy == "enhance" else settings.AI_MAX_TOKENS_PER_MINUTE
