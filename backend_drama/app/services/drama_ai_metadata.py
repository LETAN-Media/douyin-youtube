"""AI YouTube metadata generation for Drama pipelines (ToolNet, OpenAI-compatible).

Adapted from the proven backend_facebook design (facebook_ai_metadata.py):
ToolNet chat API -> localized title/description/hashtags, cache-first,
one metadata set per final video. The API key never appears in logs,
errors, or API responses.

The AI output language is per-pipeline and NEVER changes the video's
subtitle language or dub voice.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger("backend-drama.ai-metadata")

CONFIG_MISSING = "TOOLNET_CONFIG_MISSING"
AUTH_FAILED = "TOOLNET_AUTH_FAILED"
RATE_LIMITED = "TOOLNET_RATE_LIMITED"
TIMEOUT = "TOOLNET_TIMEOUT"
UPSTREAM_ERROR = "TOOLNET_UPSTREAM_ERROR"
INVALID_RESPONSE = "AI_INVALID_RESPONSE"
INSUFFICIENT_CONTEXT = "AI_INSUFFICIENT_CONTEXT"
AI_DISABLED_FOR_PIPELINE = "AI_DISABLED_FOR_PIPELINE"
AI_METADATA_FAILED = "AI_METADATA_FAILED"

MAX_RETRIES = 2

LANGUAGE_NAMES = {"vi": "TIẾNG VIỆT", "en": "ENGLISH", "zh": "简体中文"}

BASE_SYSTEM_PROMPTS: dict[str, str] = {
    "vi": """Bạn viết metadata YouTube bằng TIẾNG VIỆT cho một video phim ngắn/drama tổng hợp nhiều tập.
Yêu cầu chung: tự nhiên, dễ hiểu, hấp dẫn; không spam/clickbait rẻ tiền;
không bịa tên diễn viên, nội dung phim hay sự kiện nếu dữ liệu series không cung cấp;
không tự nhận có thông tin khi dữ liệu chưa đủ; không chèn hashtag trùng lặp;
tuân thủ giới hạn ký tự của YouTube.

Title: tiếng Việt, tối đa 100 ký tự (ưu tiên 45-80 ký tự), không ALL CAPS,
không emoji quá mức, không nhồi hashtag vào title. Phản ánh đúng phạm vi tập đã cho.

Description: tiếng Việt, 1-4 đoạn ngắn, tóm tắt đúng nội dung series và phạm vi tập,
không bịa nguồn/thông tin, tối đa 5000 ký tự (đã bao gồm hashtag khi ghép).

Hashtags: 3-6 hashtag liên quan trực tiếp nội dung, bắt đầu bằng #.

CHỈ trả đúng một JSON object, không markdown, không code fence, không text thừa:
{"title": "...", "description": "...", "hashtags": ["#...", "#..."]}""",
    "en": """You write YouTube metadata in ENGLISH for a short-drama compilation video made of multiple episodes.
General rules: natural, clear, engaging; no cheap spam/clickbait;
never invent actor names, plot details or events not provided in the series data;
never claim information you were not given; no duplicate hashtags;
respect YouTube character limits.

Title: English, max 100 characters (prefer 45-80), no ALL CAPS,
no excessive emoji, no hashtags stuffed into the title. Reflect the given episode range.

Description: English, 1-4 short paragraphs summarizing the series and the episode
range truthfully, no invented facts, max 5000 characters (including hashtags once merged).

Hashtags: 3-6 hashtags directly related to the content, each starting with #.

Return ONLY one JSON object, no markdown, no code fence, no extra text:
{"title": "...", "description": "...", "hashtags": ["#...", "#..."]}""",
    "zh": """你为一部多集合成的短剧视频撰写简体中文 YouTube 元数据。
总体要求：自然、易懂、有吸引力；不做廉价标题党/ spam；
如果剧集数据没有提供演员姓名、剧情或事件，绝不虚构；
数据不足时不要假装掌握信息；不要重复 hashtag；遵守 YouTube 字符限制。

标题：简体中文，最多100个字符（优先45-80个字符），不要全大写，
不要过多 emoji，不要在标题里堆 hashtag。要准确反映给定的集数范围。

简介：简体中文，1-4个短段落，如实概括剧集内容和集数范围，
不编造来源/信息，最多5000个字符（包含合并后的 hashtag）。

Hashtag：3-6个与内容直接相关的 hashtag，均以 # 开头。

只返回一个 JSON 对象，不要 markdown、不要代码围栏、不要多余文字：
{"title": "...", "description": "...", "hashtags": ["#...", "#..."]}""",
}

JSON_CONTRACT_FOOTER = """MANDATORY FORMAT NOTE:
Regardless of any additional instructions above, you MUST return exactly ONE plain JSON object, no code fence/markdown, no other text:
{"title": "...", "description": "...", "hashtags": ["#...", "#..."]}"""


def apply_title_template(template: str | None, title: str) -> str:
    tpl = (template or "").strip() or "{title}"
    if "{title}" not in tpl:
        tpl = "{title}"
    rendered = tpl.replace("{title}", (title or "").strip()).strip()
    return rendered[:100].rstrip()


def apply_locked_hashtags(
    locked_tags: list[str] | None,
    ai_tags: list[str] | None,
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in (ai_tags or []):
        tag = str(raw or "").strip()
        if not tag.startswith("#"):
            tag = "#" + tag.lstrip("#")
        tag = "#" + re.sub(r"\s+", "", tag[1:])
        lower = tag.lower()
        if tag != "#" and lower not in seen:
            seen.add(lower)
            result.append(tag)
    for raw in (locked_tags or []):
        tag = str(raw or "").strip()
        if not tag.startswith("#"):
            tag = "#" + tag.lstrip("#")
        tag = "#" + re.sub(r"\s+", "", tag[1:])
        lower = tag.lower()
        if tag != "#" and lower not in seen:
            seen.add(lower)
            result.append(tag)
    return result[:15]


def apply_description_template(
    template: str | None,
    description: str,
    hashtags: list[str],
    variables: dict[str, Any] | None = None,
) -> str:
    """Render {description}/{hashtags} plus dynamic vars:
    {series_title} {episode_count} {episode_start} {episode_end}
    {channel_name} {source_url} {title}."""
    tpl = (template or "").strip() or "{description}\n\n{hashtags}"
    variables = variables or {}
    hashtags_str = " ".join(hashtags)
    rendered = tpl.replace("{description}", (description or "").strip()).replace(
        "{hashtags}", hashtags_str
    )
    for key in (
        "title", "series_title", "episode_count", "episode_start",
        "episode_end", "channel_name", "source_url",
    ):
        value = variables.get(key)
        rendered = rendered.replace("{" + key + "}",
                                    "" if value is None else str(value))
    lines = [line.rstrip() for line in rendered.splitlines()]
    rendered_text = "\n".join(lines).strip()
    return rendered_text[:5000].rstrip()


def find_unreplaced_placeholders(text: str) -> list[str]:
    return sorted(set(re.findall(r"\{[A-Za-z_][A-Za-z0-9_]*\}", text or "")))


class MetadataError(Exception):
    """Typed AI error. Never carries the API key."""

    def __init__(self, code: str, message: str, usage: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.usage = usage or {}


@dataclass
class GeneratedMetadata:
    title: str
    description: str
    hashtags: list[str]
    model: str
    usage: dict


@dataclass
class ToolNetConfig:
    base_url: str
    api_key: str
    model: str
    timeout: float = 60.0


def _normalize_hashtags(raw: object) -> list[str]:
    tags: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            text = str(item or "").strip().lstrip("#").strip()
            text = re.sub(r"\s+", "", text)
            if text and text not in [t.lstrip("#") for t in tags]:
                tags.append("#" + text)
    return tags[:6]


def extract_json_object(text: str) -> dict:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
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


def validate_metadata(
    data: dict, *, context_empty: bool = False
) -> tuple[str, str, list[str]]:
    try:
        title = str(data.get("title") or "").strip()
        if not title:
            raise MetadataError(INVALID_RESPONSE, "Model response has no title.")
        if len(title) > 100:
            title = title[:100].rstrip()
        description = str(data.get("description") or "").strip()
        if len(description) > 5000:
            description = description[:5000].rstrip()
        hashtags = _normalize_hashtags(data.get("hashtags"))
        if len(hashtags) < 3:
            raise MetadataError(INVALID_RESPONSE, "Model response needs 3-6 hashtags.")
    except MetadataError as exc:
        if context_empty and exc.code == INVALID_RESPONSE:
            raise MetadataError(
                INSUFFICIENT_CONTEXT,
                "Not enough series context to write trustworthy metadata.",
            )
        raise
    return title, description, hashtags


class _SimpleRateLimiter:
    """Per-minute request/token bucket (local copy of the FB-proven design)."""

    def __init__(self, max_requests_per_minute: int, max_tokens_per_minute: int) -> None:
        self._max_req = max(1, max_requests_per_minute)
        self._max_tok = max(1, max_tokens_per_minute)
        self._req_ts: list[float] = []
        self._tok_ts: list[tuple[float, int]] = []
        self._lock = asyncio.Lock()

    async def reserve(self, estimated_tokens: int) -> None:
        async with self._lock:
            now = time.monotonic()
            self._req_ts = [t for t in self._req_ts if now - t < 60]
            self._tok_ts = [(t, n) for t, n in self._tok_ts if now - t < 60]
            used = sum(n for _, n in self._tok_ts)
            if len(self._req_ts) >= self._max_req or used + estimated_tokens > self._max_tok:
                raise MetadataError(
                    RATE_LIMITED,
                    "Local AI rate budget exhausted; retry later.",
                )
            self._req_ts.append(now)
            self._tok_ts.append((now, estimated_tokens))


_limiter: _SimpleRateLimiter | None = None


def get_limiter(max_req: int, max_tok: int) -> _SimpleRateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = _SimpleRateLimiter(max_req, max_tok)
    return _limiter


@dataclass
class DramaMetadataContext:
    series_title: str | None = None
    series_description: str | None = None
    provider: str | None = None
    episode_count: int | None = None
    episode_start: int | None = None
    episode_end: int | None = None
    processing_mode: str | None = None
    target_youtube_channel: str | None = None
    custom_prompt: str | None = None


def build_user_content(ctx: DramaMetadataContext) -> tuple[str, bool]:
    lines = [f"Phim/drama: {(ctx.series_title or '').strip() or '(chưa rõ tên)'}."]
    if (ctx.series_description or "").strip():
        lines.append(f"Mô tả gốc: {ctx.series_description.strip()[:2000]}")
    if ctx.provider:
        lines.append(f"Nguồn: {ctx.provider}")
    if ctx.episode_count:
        lines.append(f"Tổng số tập series: {ctx.episode_count}")
    if ctx.episode_start is not None or ctx.episode_end is not None:
        lines.append(f"Phạm vi tập trong video này: {ctx.episode_start or '?'}–{ctx.episode_end or '?'}")
    if ctx.processing_mode:
        lines.append(f"Chế độ xử lý video: {ctx.processing_mode} (chỉ để tham khảo, KHÔNG đổi ngôn ngữ video)")
    if ctx.target_youtube_channel:
        lines.append(f"Kênh YouTube đích: {ctx.target_youtube_channel}")
    lines.append("Hãy tạo metadata theo đúng yêu cầu hệ thống.")
    text = "\n".join(lines)
    context_empty = len((ctx.series_title or "").strip()) < 2 and len(
        (ctx.series_description or "").strip()
    ) < 10
    return text, context_empty


class DramaMetadataGenerator:
    def __init__(
        self,
        config: ToolNetConfig,
        transport: httpx.AsyncBaseTransport | None = None,
        custom_system_prompt: str | None = None,
        language: str = "vi",
    ) -> None:
        if not config.api_key:
            raise MetadataError(CONFIG_MISSING, "TOOLNET_API_KEY is not configured.")
        self.config = config
        self._transport = transport
        self.custom_system_prompt = custom_system_prompt
        self.language = (language or "vi").strip().lower() or "vi"

    @classmethod
    def from_settings(
        cls,
        transport: httpx.AsyncBaseTransport | None = None,
        model: str | None = None,
    ) -> "DramaMetadataGenerator":
        from ..config import settings

        try:
            base_url, api_key, global_model = settings.require_toolnet()
        except RuntimeError as exc:
            raise MetadataError(CONFIG_MISSING, str(exc))
        chosen = (model or "").strip() or global_model
        return cls(
            ToolNetConfig(
                base_url=base_url,
                api_key=api_key,
                model=chosen,
                timeout=settings.TOOLNET_TIMEOUT,
            ),
            transport=transport,
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

    def effective_system_prompt(self) -> str:
        lang = self.language if self.language in BASE_SYSTEM_PROMPTS else "vi"
        prompt = BASE_SYSTEM_PROMPTS[lang]
        if self.custom_system_prompt and self.custom_system_prompt.strip():
            prompt += (
                "\n\nHướng dẫn bổ sung riêng cho pipeline (vẫn phải tuân thủ "
                "mọi quy tắc nền và định dạng JSON ở trên):\n"
                + self.custom_system_prompt.strip()
            )
        prompt += f"\n\n{JSON_CONTRACT_FOOTER}"
        return prompt

    async def generate(self, ctx: DramaMetadataContext) -> GeneratedMetadata:
        from ..config import settings as _settings

        user_content, context_empty = build_user_content(ctx)
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": self.effective_system_prompt()},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.3,
            "max_tokens": 900,
        }
        limiter = get_limiter(
            _settings.TOOLNET_MAX_REQUESTS_PER_MINUTE,
            _settings.TOOLNET_MAX_TOKENS_PER_MINUTE,
        )
        estimate = len(json.dumps(payload)) // 4 + int(payload.get("max_tokens") or 0)
        await limiter.reserve(estimate)

        last_error: MetadataError | None = None
        started = time.monotonic()
        for _attempt in range(MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(
                    transport=self._transport, timeout=self.config.timeout
                ) as client:
                    resp = await client.post(
                        f"{self.config.base_url}/chat/completions",
                        headers=self._headers(),
                        json=payload,
                    )
            except httpx.TimeoutException as exc:
                last_error = MetadataError(TIMEOUT, f"ToolNet timeout: {type(exc).__name__}.")
                continue
            except (httpx.ConnectError, httpx.NetworkError) as exc:
                last_error = MetadataError(
                    UPSTREAM_ERROR, f"ToolNet unreachable: {type(exc).__name__}."
                )
                break
            if resp.status_code == 401:
                raise MetadataError(AUTH_FAILED, "ToolNet credential invalid (401).")
            if resp.status_code == 429:
                last_error = MetadataError(RATE_LIMITED, "ToolNet rate limited (429).")
                continue
            if resp.status_code == 400:
                raise MetadataError(INVALID_RESPONSE, "ToolNet rejected the request (400).")
            if 500 <= resp.status_code <= 599:
                last_error = MetadataError(
                    UPSTREAM_ERROR, f"ToolNet error ({resp.status_code})."
                )
                continue
            if resp.status_code != 200:
                raise MetadataError(UPSTREAM_ERROR, f"ToolNet failed ({resp.status_code}).")
            _, content, usage = parse_chat_body(resp.text)
            data = extract_json_object(content if isinstance(content, str) else "")
            title, description, hashtags = validate_metadata(
                data, context_empty=context_empty
            )
            latency = round(time.monotonic() - started, 1)
            logger.info(
                "drama metadata generated lang=%s model=%s latency=%ss",
                self.language, self.config.model, latency,
            )
            return GeneratedMetadata(
                title=title,
                description=description,
                hashtags=hashtags,
                model=self.config.model,
                usage=usage if isinstance(usage, dict) else {},
            )
        assert last_error is not None
        raise last_error


@dataclass
class EnsureMetadataResult:
    metadata: GeneratedMetadata
    cached: bool
    model: str
    usage: dict


def _series_episode_count(series_id: str) -> int | None:
    try:
        from ..db.repositories import drama as drama_repo

        episodes = drama_repo.list_episodes(series_id) or []
        return len(episodes) or None
    except Exception:
        return None


def build_context_for_job(
    *,
    job: dict[str, Any],
    series: dict[str, Any] | None,
    channel_title: str | None,
    custom_prompt: str | None = None,
) -> DramaMetadataContext:
    series = series or {}
    return DramaMetadataContext(
        series_title=series.get("title"),
        series_description=series.get("description"),
        provider=series.get("provider") or job.get("provider"),
        episode_count=_series_episode_count(job.get("series_id") or "")
        or series.get("episode_count"),
        episode_start=job.get("episode_start"),
        episode_end=job.get("episode_end"),
        processing_mode=job.get("processing_mode"),
        target_youtube_channel=channel_title,
        custom_prompt=custom_prompt,
    )


async def ensure_drama_ai_metadata(
    job: dict[str, Any],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    force_regenerate: bool = False,
) -> EnsureMetadataResult:
    """Cache-first metadata for ONE final video (one job = one set).

    Raises MetadataError (AI_DISABLED_FOR_PIPELINE when the pipeline has
    AI off, INSUFFICIENT_CONTEXT, upstream errors...).
    """
    from ..config import settings as app_settings
    from ..db.repositories import ai_metadata as cache_repo
    from ..db.repositories import drama as drama_repo
    from ..db.repositories import youtube as yt_repo

    job_id = job["id"]
    pipeline_id = job.get("pipeline_id") or ""
    series_id = job.get("series_id") or ""

    cfg, config_hash = cache_repo.current_config_hash(
        pipeline_id, model=(app_settings.TOOLNET_MODEL or "").strip() or None
    )
    if not app_settings.TOOLNET_AI_ENABLED:
        raise MetadataError(CONFIG_MISSING, "TOOLNET_AI_ENABLED is off.")
    if not cfg.get("enabled"):
        raise MetadataError(
            AI_DISABLED_FOR_PIPELINE,
            f"AI metadata is disabled for pipeline {pipeline_id}.",
        )

    language = cfg.get("language") or "vi"
    series = drama_repo.get_series(series_id) if series_id else None
    channel_title: str | None = None
    try:
        from ..db.repositories import processing as proc_repo

        settings_row = proc_repo.get_settings(pipeline_id) or {}
        dest_id = settings_row.get("youtube_destination_id")
        if dest_id:
            dest = yt_repo.get_destination(dest_id) or {}
            channel_title = dest.get("channel_title") or dest.get("channel_id")
    except Exception:
        channel_title = None

    ctx = build_context_for_job(
        job=job, series=series, channel_title=channel_title,
        custom_prompt=cfg.get("system_prompt"),
    )
    _, context_empty = build_user_content(ctx)
    src_hash = cache_repo.source_hash(
        (series or {}).get("title"), (series or {}).get("description"),
        job.get("episode_start"), job.get("episode_end"), language,
    )

    if not force_regenerate:
        cached = cache_repo.get_cache_row(job_id, language)
        if (
            cached is not None
            and cached.get("config_hash") == config_hash
            and cached.get("source_hash") == src_hash
            and (cached.get("title") or "").strip()
        ):
            return EnsureMetadataResult(
                metadata=GeneratedMetadata(
                    title=cached["title"],
                    description=cached.get("description") or "",
                    hashtags=cached.get("hashtags") or [],
                    model=cached.get("model") or "",
                    usage={},
                ),
                cached=True,
                model=cached.get("model") or "",
                usage={},
            )

    generator = DramaMetadataGenerator.from_settings(
        transport=transport,
        model=(cfg.get("model_override") or "").strip() or None,
    )
    generator.custom_system_prompt = cfg.get("system_prompt") or ""
    generator.language = language
    generated = await generator.generate(ctx)

    title = generated.title if cfg.get("generate_title", True) else ""
    description = generated.description if cfg.get("generate_description", True) else ""
    hashtags = generated.hashtags if cfg.get("generate_hashtags", True) else []
    if cfg.get("generate_title", True) and not title.strip():
        raise MetadataError(INVALID_RESPONSE, "Model response has no title.")
    series_dict = series or {}
    tpl_vars = {
        "title": title,
        "series_title": series_dict.get("title"),
        "episode_count": series_dict.get("total_episodes")
        or series_dict.get("episode_count"),
        "episode_start": job.get("episode_start"),
        "episode_end": job.get("episode_end"),
        "channel_name": channel_title,
        "source_url": series_dict.get("source_url"),
    }
    final_title = apply_title_template(cfg.get("title_template"), title)
    final_hashtags = apply_locked_hashtags(cfg.get("locked_hashtags"), hashtags)
    final_description = apply_description_template(
        cfg.get("description_template"), description, final_hashtags,
        variables=tpl_vars,
    )
    if not final_title.strip():
        raise MetadataError(INVALID_RESPONSE, "Title template produced an empty title.")
    leftover = find_unreplaced_placeholders(final_title)
    if leftover:
        raise MetadataError(
            INVALID_RESPONSE, f"Title has unreplaced placeholders: {leftover}."
        )
    leftover = find_unreplaced_placeholders(final_description)
    if leftover:
        raise MetadataError(
            INVALID_RESPONSE,
            f"Description has unreplaced placeholders: {leftover}.",
        )

    cache_repo.upsert_cache(
        pipeline_id=pipeline_id,
        series_id=series_id,
        job_id=job_id,
        language=language,
        config_hash=config_hash,
        source_hash=src_hash,
        model=generated.model,
        title=final_title,
        description=final_description,
        hashtags=final_hashtags,
    )
    return EnsureMetadataResult(
        metadata=GeneratedMetadata(
            title=final_title,
            description=final_description,
            hashtags=final_hashtags,
            model=generated.model,
            usage=generated.usage,
        ),
        cached=False,
        model=generated.model,
        usage=generated.usage,
    )
