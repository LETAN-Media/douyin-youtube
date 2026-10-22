"""Per-pipeline AI YouTube metadata (ToolNet, OpenAI-compatible).

Same proven shape as backend_drama: localized base prompts + per-pipeline
system prompt/genre/templates, strict JSON validation, config-hash cache key.
One final video = one metadata set unless the user regenerates.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger("backend-audio.ai")

CONFIG_MISSING = "TOOLNET_CONFIG_MISSING"
AUTH_FAILED = "TOOLNET_AUTH_FAILED"
RATE_LIMITED = "TOOLNET_RATE_LIMITED"
TIMEOUT = "TOOLNET_TIMEOUT"
UPSTREAM_ERROR = "TOOLNET_UPSTREAM_ERROR"
INVALID_RESPONSE = "AI_INVALID_RESPONSE"
AI_DISABLED = "AI_DISABLED_FOR_PIPELINE"

MAX_RETRIES = 2

BASE_PROMPTS: dict[str, str] = {
    "vi": """Bạn viết metadata YouTube bằng TIẾNG VIỆT cho một video truyện audio (audio truyện đọc trên nền video loop).
Không bịa tên truyện/nhân vật/tình tiết nếu dữ liệu không cung cấp. Không lặp hashtag.
Title: tối đa 100 ký tự, hấp dẫn, chuẩn tìm kiếm YouTube.
Description: tóm tắt đúng nội dung, tối đa 5000 ký tự (đã gồm hashtag khi ghép).
Hashtags: 3-6 cái liên quan trực tiếp.
CHỈ trả đúng một JSON object, không markdown: {"title": "...", "description": "...", "hashtags": ["#...", "#..."]}""",
    "en": """You write YouTube metadata in ENGLISH for an audio-story video (narrated story over a looped background).
Never invent story/character/plot details not provided. No duplicate hashtags.
Title: max 100 chars, catchy, YouTube-search friendly.
Description: truthful summary, max 5000 chars (incl. hashtags once merged).
Hashtags: 3-6 directly related.
Return ONLY one JSON object, no markdown: {"title": "...", "description": "...", "hashtags": ["#...", "#..."]}""",
    "zh": """你为音频故事视频（朗读配循环背景）撰写简体中文 YouTube 元数据。
没有提供的人物/剧情绝不虚构。不要重复 hashtag。
标题：最多100字符，有吸引力，利于搜索。
简介：如实概括，最多5000字符（含合并后的 hashtag）。
Hashtag：3-6个直接相关。
只返回一个 JSON 对象，不要 markdown：{"title": "...", "description": "...", "hashtags": ["#...", "#..."]}""",
}

JSON_FOOTER = """MANDATORY: return exactly ONE plain JSON object, no code fence, no other text:
{"title": "...", "description": "...", "hashtags": ["#...", "#..."]}"""


class MetadataError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class GeneratedMetadata:
    title: str
    description: str
    hashtags: list[str]
    model: str
    usage: dict


@dataclass
class AiContext:
    genre: str | list[str] | None = None
    source_title: str | None = None
    source_caption: str | None = None
    audio_duration_s: float | None = None
    transcript_summary: str | None = None
    channel_name: str | None = None
    custom_prompt: str | None = None


def normalize_language(value: Any) -> str:
    lang = str(value or "").strip().lower()
    if lang in ("vn", "vietnamese"):
        return "vi"
    if lang in ("english",):
        return "en"
    if lang in ("chinese", "中文"):
        return "zh"
    return lang if lang in ("vi", "en", "zh") else "vi"


def apply_title_template(template: str | None, title: str) -> str:
    tpl = (template or "").strip() or "{title}"
    if "{title}" not in tpl.lower():
        tpl = "{title}"
    pattern = re.compile(re.escape("{title}"), re.IGNORECASE)
    return pattern.sub((title or "").strip(), tpl).strip()[:100].rstrip()


def apply_locked_hashtags(locked: list[str] | None,
                           ai_tags: list[str] | None) -> list[str]:
    result, seen = [], set()
    for raw in (ai_tags or []) + (locked or []):
        tag = str(raw or "").strip()
        if not tag.startswith("#"):
            tag = "#" + tag.lstrip("#")
        tag = "#" + re.sub(r"\s+", "", tag[1:])
        if tag != "#" and tag.lower() not in seen:
            seen.add(tag.lower())
            result.append(tag)
    return result[:15]


def apply_description_template(template: str | None, description: str,
                               hashtags: list[str]) -> str:
    tpl = (template or "").strip() or "{description}\n\n{hashtags}"
    pattern_desc = re.compile(re.escape("{description}"), re.IGNORECASE)
    pattern_tags = re.compile(re.escape("{hashtags}"), re.IGNORECASE)
    rendered = pattern_desc.sub((description or "").strip(), tpl)
    rendered = pattern_tags.sub(" ".join(hashtags), rendered)
    lines = [line.rstrip() for line in rendered.splitlines()]
    return "\n".join(lines).strip()[:5000].rstrip()


def extract_json_object(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*", "", (text or "").strip())
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    raise MetadataError(INVALID_RESPONSE, "Model did not return a JSON object.")


def parse_chat_body(raw_text: str) -> tuple[dict, str, dict]:
    text = (raw_text or "").strip()
    if "data: [DONE]" in text:
        text = text.split("data: [DONE]")[0].strip()
    try:
        body = json.loads(text)
    except Exception:
        body = None
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("data:"):
                continue
            try:
                candidate = json.loads(line)
            except Exception:
                continue
            if isinstance(candidate, dict):
                body = candidate
                break
    if not isinstance(body, dict):
        raise MetadataError(INVALID_RESPONSE, "ToolNet response has no usable content.")
    try:
        content = body["choices"][0]["message"]["content"]
        usage = body.get("usage") or {}
    except Exception:
        raise MetadataError(INVALID_RESPONSE, "ToolNet response has no usable content.")
    return body, content, usage


def validate_metadata(data: dict) -> tuple[str, str, list[str]]:
    title = str(data.get("title") or "").strip()[:100].rstrip()
    if not title:
        raise MetadataError(INVALID_RESPONSE, "Model response has no title.")
    description = str(data.get("description") or "").strip()[:5000].rstrip()
    tags: list[str] = []
    if isinstance(data.get("hashtags"), list):
        for item in data["hashtags"]:
            text = re.sub(r"\s+", "", str(item or "").strip().lstrip("#"))
            if text and text not in [t.lstrip("#") for t in tags]:
                tags.append("#" + text)
    tags = tags[:6]
    if len(tags) < 3:
        raise MetadataError(INVALID_RESPONSE, "Model response needs 3-6 hashtags.")
    return title, description, tags


class _RateLimiter:
    def __init__(self, max_req: int, max_tok: int) -> None:
        self._max_req, self._max_tok = max(1, max_req), max(1, max_tok)
        self._req: list[float] = []
        self._lock = asyncio.Lock()

    async def reserve(self) -> None:
        async with self._lock:
            now = time.monotonic()
            self._req = [t for t in self._req if now - t < 60]
            if len(self._req) >= self._max_req:
                raise MetadataError(RATE_LIMITED, "Local AI rate budget exhausted.")
            self._req.append(now)


_limiter: _RateLimiter | None = None


async def generate_metadata(ctx: AiContext, settings_row: dict,
                            transport: httpx.AsyncBaseTransport | None = None,
                            model: str | None = None) -> GeneratedMetadata:
    from app.config import settings as app_settings

    if not app_settings.TOOLNET_AI_ENABLED:
        raise MetadataError(CONFIG_MISSING, "TOOLNET_AI_ENABLED is off.")
    try:
        base_url, api_key, global_model = app_settings.require_toolnet()
    except RuntimeError as exc:
        raise MetadataError(CONFIG_MISSING, str(exc))
    language = normalize_language(settings_row.get("language"))
    chosen = ((settings_row.get("model_override") or "").strip()
              or (model or "").strip() or global_model)
    global _limiter
    if _limiter is None:
        _limiter = _RateLimiter(app_settings.TOOLNET_MAX_REQUESTS_PER_MINUTE,
                                app_settings.TOOLNET_MAX_TOKENS_PER_MINUTE)
    await _limiter.reserve()

    system = BASE_PROMPTS[language]
    if isinstance(ctx.genre, list):
        genres = []
        for g in ctx.genre:
            for part in str(g).split(","):
                cleaned = re.sub(r"[\[\]\'\"\\\\]+", "", part).strip()
                if cleaned and cleaned not in genres:
                    genres.append(cleaned)
        genre_text = ", ".join(genres)
    else:
        genre_text = re.sub(r"[\[\]\'\"\\\\]+", "", str(ctx.genre or "")).strip()
    if genre_text:
        system += f"\nThể loại nội dung: {genre_text}"
    if settings_row.get("system_prompt"):
        system += ("\n\nHướng dẫn riêng của pipeline (vẫn tuân thủ mọi quy tắc "
                   "nền và định dạng JSON):\n" + settings_row["system_prompt"].strip())
    system += f"\n\n{JSON_FOOTER}"

    user_lines = []
    if ctx.source_title:
        user_lines.append(f"Tiêu đề nguồn: {ctx.source_title}")
    if ctx.source_caption:
        user_lines.append(f"Caption nguồn: {ctx.source_caption[:2000]}")
    if ctx.audio_duration_s:
        user_lines.append(f"Thời lượng audio: {ctx.audio_duration_s / 60:.1f} phút")
    if ctx.transcript_summary:
        user_lines.append(f"Tóm tắt transcript: {ctx.transcript_summary[:3000]}")
    if ctx.channel_name:
        user_lines.append(f"Kênh đích: {ctx.channel_name}")
    user_lines.append("Hãy tạo metadata theo đúng yêu cầu hệ thống.")

    fallback_model = (app_settings.TOOLNET_FALLBACK_MODEL or "").strip()
    models = [chosen]
    if fallback_model and fallback_model != chosen:
        models.append(fallback_model)

    last_error: MetadataError | None = None
    for model_index, attempt_model in enumerate(models):
        payload = {
            "model": attempt_model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": "\n".join(user_lines)}],
            "temperature": 0.3,
            "max_tokens": 900,
        }
        model_error: MetadataError | None = None
        for _ in range(MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(
                        transport=transport,
                        timeout=app_settings.TOOLNET_TIMEOUT) as client:
                    resp = await client.post(f"{base_url}/chat/completions",
                                             headers={
                                                 "Authorization": f"Bearer {api_key}",
                                                 "Content-Type": "application/json"},
                                             json=payload)
            except httpx.TimeoutException:
                model_error = MetadataError(TIMEOUT, "ToolNet timeout.")
                continue
            except (httpx.ConnectError, httpx.NetworkError):
                model_error = MetadataError(UPSTREAM_ERROR, "ToolNet unreachable.")
                break
            if resp.status_code == 401:
                raise MetadataError(AUTH_FAILED, "ToolNet credential invalid (401).")
            if resp.status_code == 429:
                model_error = MetadataError(RATE_LIMITED, "ToolNet rate limited (429).")
                continue
            if 500 <= resp.status_code <= 599:
                model_error = MetadataError(
                    UPSTREAM_ERROR, f"ToolNet error ({resp.status_code}).")
                continue
            if resp.status_code != 200:
                model_error = MetadataError(
                    UPSTREAM_ERROR, f"ToolNet HTTP {resp.status_code}.")
                break
            try:
                _, content, usage = parse_chat_body(resp.text)
                data = extract_json_object(content if isinstance(content, str) else "")
                title, description, hashtags = validate_metadata(data)
                final_title = (apply_title_template(settings_row.get("title_template"), title)
                               if settings_row.get("generate_title", True) else "")
                final_tags = (apply_locked_hashtags(
                    _parse_locked(settings_row.get("locked_hashtags_json")), hashtags)
                    if settings_row.get("generate_hashtags", True) else
                    apply_locked_hashtags(
                        _parse_locked(settings_row.get("locked_hashtags_json")), []))
                final_desc = (apply_description_template(
                    settings_row.get("description_template"), description, final_tags)
                    if settings_row.get("generate_description", True) else "")
                if not final_title.strip():
                    raise MetadataError(INVALID_RESPONSE, "Empty title after template.")
                return GeneratedMetadata(title=final_title, description=final_desc,
                                         hashtags=final_tags, model=attempt_model,
                                         usage=usage if isinstance(usage, dict) else {})
            except MetadataError as me:
                model_error = me
                continue
        last_error = model_error or MetadataError(
            INVALID_RESPONSE, "ToolNet returned no usable response.")
        if model_index + 1 < len(models):
            logger.warning("AI model %s failed (%s: %s); falling back to %s",
                           attempt_model, last_error.code, last_error,
                           models[model_index + 1])
    assert last_error is not None
    raise last_error


def _parse_locked(raw: Any) -> list[str]:
    try:
        items = json.loads(raw or "[]")
        return [str(x) for x in items if str(x).strip()]
    except Exception:
        return []


def config_hash_for(settings_row: dict, model: str) -> str:
    genre = settings_row.get("genre")
    genre_text = (", ".join(sorted(str(g).strip() for g in genre if str(g).strip()))
                  if isinstance(genre, list) else str(genre or "").strip())
    canonical = json.dumps({
        "enabled": bool(settings_row.get("enabled")),
        "language": normalize_language(settings_row.get("language")),
        "genre": genre_text,
        "generate_title": bool(settings_row.get("generate_title", True)),
        "generate_description": bool(settings_row.get("generate_description", True)),
        "generate_hashtags": bool(settings_row.get("generate_hashtags", True)),
        "system_prompt": (settings_row.get("system_prompt") or "").strip(),
        "title_template": (settings_row.get("title_template") or "").strip(),
        "description_template": (settings_row.get("description_template") or "").strip(),
        "locked": sorted(_parse_locked(settings_row.get("locked_hashtags_json"))),
        "model": (model or "").strip(),
        "config_version": int(settings_row.get("config_version") or 0),
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]
