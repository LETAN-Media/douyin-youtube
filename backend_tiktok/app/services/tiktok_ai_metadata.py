"""AI metadata generation via ToolNet — with pipeline-level settings."""

import json
import logging
import re
from typing import Any

from ..config import settings
from ..db.repositories import ai_metadata, ai_settings

logger = logging.getLogger("backend-tiktok.services.ai_metadata")


async def generate_ai_metadata(
    ai_model: str | None = None,
    reel: dict[str, Any] | None = None,
    original_caption: str | None = None,
    pipeline_id: str | None = None,
    override_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate YouTube-optimized title, description, hashtags for a reel.

    Respects pipeline-specific AI Settings (system prompt, title rules, tone,
    emoji rules, locked hashtags, required/forbidden keywords).
    """
    reel_dict = reel or {}
    caption = original_caption or reel_dict.get("caption") or ""
    thumbnail_desc = reel_dict.get("thumbnail_url") or ""

    # 1. Resolve pipeline_id if not explicitly provided
    resolved_pipeline_id = pipeline_id or reel_dict.get("pipeline_id")
    if not resolved_pipeline_id and reel_dict.get("source_id"):
        from ..db.repositories import sources as sources_repo

        src = await sources_repo.get_source(reel_dict["source_id"])
        if src:
            resolved_pipeline_id = src.get("pipeline_id")

    # 2. Load settings for this pipeline
    if resolved_pipeline_id:
        cfg = await ai_settings.get_ai_settings(resolved_pipeline_id)
    else:
        cfg = dict(ai_settings.DEFAULT_AI_SETTINGS)

    if override_settings:
        cfg = {**cfg, **override_settings}

    if not cfg.get("enabled", True):
        logger.info("AI metadata generation disabled for pipeline %s", resolved_pipeline_id)
        fallback_title = (caption[:90] if caption else "TikTok Video").strip()
        return {
            "title": fallback_title,
            "description": caption,
            "hashtags": ["#shorts"],
            "hashtags_json": json.dumps(["#shorts"]),
            "model": "disabled",
            "provider": cfg.get("provider", "toolnet"),
        }

    # 3. Model & prompts
    model = (
        ai_model
        or cfg.get("model")
        or settings.toolnet_model
        or "groq/openai/gpt-oss-120b"
    )
    provider = cfg.get("provider", "toolnet")
    system = (
        cfg.get("system_prompt")
        or ai_settings.DEFAULT_AI_SETTINGS["system_prompt"]
    )

    prompt = _build_advanced_prompt(
        caption=caption,
        thumbnail_hint=thumbnail_desc,
        title_prompt=cfg.get("title_prompt") or "",
        description_prompt=cfg.get("description_prompt") or "",
        hashtag_prompt=cfg.get("hashtag_prompt") or "",
        language=cfg.get("language") or "vi",
        max_hashtags=int(cfg.get("max_hashtags") or 10),
        include_emojis=bool(cfg.get("include_emojis", True)),
        tone=cfg.get("tone") or "engaging",
        required_keywords=cfg.get("required_keywords") or "",
        forbidden_keywords=cfg.get("forbidden_keywords") or "",
    )

    result = await _call_toolnet(prompt, system, model)

    # 4. Post-processing & templating
    raw_title = result.get("title") or caption[:80] or "TikTok Video"
    raw_desc = result.get("description") or caption
    raw_tags = result.get("hashtags") or []

    # Merge locked hashtags
    locked = cfg.get("locked_hashtags") or []
    seen = set()
    merged_tags: list[str] = []

    for tag in [*locked, *raw_tags]:
        clean_tag = str(tag).strip()
        if not clean_tag.startswith("#"):
            clean_tag = f"#{clean_tag}"
        lower_tag = clean_tag.lower()
        if lower_tag not in seen and len(clean_tag) > 1:
            seen.add(lower_tag)
            merged_tags.append(clean_tag)

    max_tags = int(cfg.get("max_hashtags") or 10)
    final_tags = merged_tags[:max_tags]
    if not final_tags:
        final_tags = ["#shorts"]

    # Apply title template
    tpl_title = cfg.get("title_template") or "{title}"
    if "{title}" in tpl_title:
        final_title = tpl_title.replace("{title}", raw_title).strip()
    else:
        final_title = raw_title.strip()
    final_title = final_title[:100]

    # Apply description template
    tpl_desc = cfg.get("description_template") or "{description}\n\n{hashtags}"
    final_desc = (
        tpl_desc.replace("{description}", raw_desc)
        .replace("{hashtags}", " ".join(final_tags))
        .replace("{title}", final_title)
        .replace("{source_url}", reel_dict.get("reel_url") or "")
        .strip()
    )

    return {
        "title": final_title,
        "description": final_desc,
        "hashtags": final_tags,
        "hashtags_json": json.dumps(final_tags),
        "model": model,
        "provider": provider,
    }


def _build_advanced_prompt(
    caption: str,
    thumbnail_hint: str,
    title_prompt: str,
    description_prompt: str,
    hashtag_prompt: str,
    language: str,
    max_hashtags: int,
    include_emojis: bool,
    tone: str,
    required_keywords: str,
    forbidden_keywords: str,
) -> str:
    lang_map = {"vi": "Tiếng Việt", "en": "English", "zh": "中文", "ja": "日本語"}
    lang_name = lang_map.get(language, language)

    lines = [
        f"Hãy tạo tiêu đề, mô tả và hashtag cho video TikTok đăng lên YouTube Shorts bằng {lang_name}.",
        f"- Nội dung video gốc / caption: {caption[:600] if caption else '(không có nội dung chữ)'}",
    ]
    if thumbnail_hint:
        lines.append(f"- Thông tin thumbnail: {thumbnail_hint}")

    lines.append(f"- Giọng văn (Tone): {tone}")
    lines.append(f"- Sử dụng Emoji: {'Có, tự nhiên và sinh động' if include_emojis else 'Không sử dụng bất kỳ emoji nào'}")

    if title_prompt:
        lines.append(f"- Quy tắc tiêu đề: {title_prompt}")
    else:
        lines.append("- Quy tắc tiêu đề: Hấp dẫn, kích thích tò mò, dài 60-90 ký tự.")

    if description_prompt:
        lines.append(f"- Quy tắc mô tả: {description_prompt}")
    else:
        lines.append("- Quy tắc mô tả: 2-3 đoạn ngắn tóm tắt nội dung, có lời kêu gọi xem và đăng ký.")

    if hashtag_prompt:
        lines.append(f"- Quy tắc hashtag: {hashtag_prompt}")
    lines.append(f"- Số hashtag: Tối đa {max_hashtags} hashtag thịnh hành bắt đầu bằng dấu #.")

    if required_keywords.strip():
        lines.append(f"- Từ khóa BẮT BUỘC phải xuất hiện trong tiêu đề hoặc mô tả: {required_keywords.strip()}")

    if forbidden_keywords.strip():
        lines.append(f"- Từ khóa TUYỆT ĐỐI CẤM không được xuất hiện: {forbidden_keywords.strip()}")

    lines.append(
        "Yêu cầu định dạng đầu ra: Bắt buộc trả về duy nhất một chuỗi JSON hợp lệ không bọc markdown thừa, "
        'với cấu trúc: {"title": "...", "description": "...", "hashtags": ["#tag1", "#tag2"]}'
    )
    return "\n".join(lines)


async def _call_toolnet(prompt: str, system: str, model: str) -> dict[str, Any]:
    import asyncio

    if not settings.toolnet_base_url or not settings.toolnet_api_key:
        logger.warning("ToolNet not configured, using heuristic fallback")
        return {
            "title": prompt.split("\n")[1][:80],
            "description": prompt.split("\n")[1],
            "hashtags": ["#shorts"],
        }

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, _call_toolnet_sync, prompt, system, model
    )


def _call_toolnet_sync(prompt: str, system: str, model: str) -> dict[str, Any]:
    import httpx

    api_key = settings.toolnet_api_key
    base_url = settings.toolnet_base_url.rstrip("/")

    resp = httpx.post(
        f"{base_url}/chat/completions",
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
        raise RuntimeError(f"ToolNet API error: {resp.status_code} - {resp.text[:200]}")

    data = resp.json()
    text = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
    text = text.strip()

    # Clean markdown fences
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        return json.loads(text)
    except Exception:
        # Fallback regex if LLM outputs extra comments
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass
        return {"title": text[:80], "description": text, "hashtags": ["#shorts"]}

        return json.loads(text)
    except json.JSONDecodeError:
        return {"title": None, "description": text, "hashtags": []}
