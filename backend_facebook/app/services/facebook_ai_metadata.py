"""YouTube metadata generation via ToolNet AI (Task 8A).

Facebook Reel caption -> ToolNet OpenAI-compatible chat API -> Vietnamese
title/description/hashtags, persisted per reel. The API key never appears
in logs, errors, or API responses.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass

import httpx

from .ai_rate_limit import RateLimitExceeded, get_shared_limiter

logger = logging.getLogger("backend-facebook.ai-metadata")

CONFIG_MISSING = "TOOLNET_CONFIG_MISSING"
AUTH_FAILED = "TOOLNET_AUTH_FAILED"
RATE_LIMITED = "TOOLNET_RATE_LIMITED"
TIMEOUT = "TOOLNET_TIMEOUT"
UPSTREAM_ERROR = "TOOLNET_UPSTREAM_ERROR"
INVALID_RESPONSE = "AI_INVALID_RESPONSE"
INSUFFICIENT_CONTEXT = "AI_INSUFFICIENT_CONTEXT"
AI_DISABLED_FOR_PIPELINE = "AI_DISABLED_FOR_PIPELINE"

MAX_RETRIES = 2
FALLBACK_CONTEXT = (
    "Đây là một Facebook Reel. Hãy tạo metadata trung tính dựa trên thông tin có sẵn."
)

BASE_SYSTEM_PROMPT = """Bạn viết metadata YouTube bằng TIẾNG VIỆT cho một Facebook Reel.
Yêu cầu chung: tự nhiên, dễ hiểu, hấp dẫn; không spam/clickbait rẻ tiền;
không bịa thông tin không có trong caption; không thêm tên người/sự kiện
nếu nguồn không có; giữ đúng nội dung Reel; tối ưu để người Việt dễ đọc.

Title: tiếng Việt, tối đa 100 ký tự (ưu tiên 45-80 ký tự), không ALL CAPS,
không emoji quá mức, không nhồi hashtag vào title.

Description: tiếng Việt, 1-3 đoạn ngắn, tóm tắt đúng nội dung, không bịa
nguồn/thông tin, tối đa 1500 ký tự.

Hashtags: 3-6 hashtag liên quan trực tiếp nội dung, không vô nghĩa, bắt đầu bằng #.

CHỈ trả đúng một JSON object, không markdown, không code fence, không text thừa:
{"title": "...", "description": "...", "hashtags": ["#...", "#..."]}"""

# Legacy alias
SYSTEM_PROMPT = BASE_SYSTEM_PROMPT

JSON_CONTRACT_FOOTER = """CHÚ Ý QUAN TRỌNG VỀ ĐỊNH DẠNG BẮT BUỘC:
Bất kể hướng dẫn bổ sung nào ở trên, bạn BẮT BUỘC CHỈ trả về đúng 1 JSON object thuần túy, không dùng code fence/markdown, không có text nào khác ngoài JSON:
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
    return result


def apply_description_template(
    template: str | None,
    description: str,
    hashtags: list[str],
    source_url: str | None = None,
) -> str:
    tpl = (template or "").strip() or "{description}\n\n{hashtags}"
    hashtags_str = " ".join(hashtags)
    rendered = (
        tpl.replace("{description}", (description or "").strip())
        .replace("{hashtags}", hashtags_str)
        .replace("{source_url}", (source_url or "").strip())
    )
    lines = [line.rstrip() for line in rendered.splitlines()]
    rendered_text = "\n".join(lines).strip()
    return rendered_text[:5000].rstrip()


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
    """Parse model output; tolerates surrounding code fences/text."""
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
    """Parse a chat-completions body; tolerates SSE trailers like `data: [DONE]`.

    Returns (body, content, usage). Raises MetadataError(INVALID_RESPONSE).
    """
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


def validate_metadata(data: dict, *, context_empty: bool = False) -> tuple[str, str, list[str]]:
    try:
        title = str(data.get("title") or "").strip()
        if not title:
            raise MetadataError(INVALID_RESPONSE, "Model response has no title.")
        if len(title) > 100:
            title = title[:100].rstrip()
        description = str(data.get("description") or "").strip()
        if len(description) > 1500:
            description = description[:1500].rstrip()
        hashtags = _normalize_hashtags(data.get("hashtags"))
        if len(hashtags) < 3:
            raise MetadataError(INVALID_RESPONSE, "Model response needs 3-6 hashtags.")
    except MetadataError as exc:
        if context_empty and exc.code == INVALID_RESPONSE:
            raise MetadataError(
                INSUFFICIENT_CONTEXT,
                "Not enough context to write trustworthy metadata.",
            )
        raise
    return title, description, hashtags


class FacebookMetadataGenerator:
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
        self.language = language or "vi"

    @classmethod
    def from_settings(
        cls,
        transport: httpx.AsyncBaseTransport | None = None,
        model: str | None = None,
    ) -> "FacebookMetadataGenerator":
        from ..config import settings

        try:
            base_url, api_key, global_model = settings.require_toolnet()
        except RuntimeError as exc:
            raise MetadataError(CONFIG_MISSING, str(exc))
        chosen = (model or "").strip() or global_model
        return cls(
            ToolNetConfig(
                base_url=base_url, api_key=api_key, model=chosen,
                timeout=settings.TOOLNET_TIMEOUT,
            ),
            transport=transport,
        )

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.api_key}", "Content-Type": "application/json"}

    async def generate(
        self,
        reel_id: str,
        caption: str | None,
        reel_url: str | None = None,
    ) -> GeneratedMetadata:
        caption_text = (caption or "").strip()
        context_empty = len(caption_text) < 3
        context = caption_text if not context_empty else FALLBACK_CONTEXT
        user_content = (
            f"Facebook Reel (reel_id={reel_id}).\n"
            f"Caption gốc: {context}\n"
            + (f"URL nguồn: {reel_url}\n" if reel_url else "")
            + "Hãy tạo metadata theo đúng yêu cầu hệ thống."
        )
        effective_prompt = BASE_SYSTEM_PROMPT
        lang = (self.language or "vi").strip().lower()
        if lang != "vi":
            effective_prompt += f"\n\nNgôn ngữ đầu ra ưu tiên: {lang}."
        if self.custom_system_prompt and self.custom_system_prompt.strip():
            effective_prompt += f"\n\nHướng dẫn bổ sung riêng cho kênh/pipeline:\n{self.custom_system_prompt.strip()}"
        effective_prompt += f"\n\n{JSON_CONTRACT_FOOTER}"

        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": effective_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.3,
            "max_tokens": 800,
        }

        last_error: MetadataError | None = None
        started = time.monotonic()
        estimate = len(json.dumps(payload)) // 4 + int(payload.get("max_tokens") or 0)
        from ..config import settings as _settings

        limiter = get_shared_limiter(
            _settings.TOOLNET_MAX_REQUESTS_PER_MINUTE,
            _settings.TOOLNET_MAX_TOKENS_PER_MINUTE,
        )
        try:
            await limiter.reserve(estimate)
        except RateLimitExceeded as exc:
            raise MetadataError(RATE_LIMITED, str(exc))
        settled = False
        try:
            for attempt in range(MAX_RETRIES + 1):
                try:
                    async with httpx.AsyncClient(
                        transport=self._transport, timeout=self.config.timeout
                    ) as client:
                        resp = await client.post(
                            f"{self.config.base_url}/chat/completions",
                            headers=self._headers(),
                            json=payload,
                        )
                except (httpx.TimeoutException,) as exc:
                    last_error = MetadataError(TIMEOUT, f"ToolNet timeout: {type(exc).__name__}.")
                    continue
                except (httpx.ConnectError, httpx.NetworkError) as exc:
                    last_error = MetadataError(UPSTREAM_ERROR, f"ToolNet unreachable: {type(exc).__name__}.")
                    break
                if resp.status_code == 401:
                    raise MetadataError(AUTH_FAILED, "ToolNet credential invalid (401).")
                if resp.status_code == 429:
                    last_error = MetadataError(RATE_LIMITED, "ToolNet rate limited (429).")
                    continue
                if resp.status_code == 400:
                    raise MetadataError(INVALID_RESPONSE, "ToolNet rejected the request (400).")
                if 500 <= resp.status_code <= 599:
                    last_error = MetadataError(UPSTREAM_ERROR, f"ToolNet error ({resp.status_code}).")
                    continue
                if resp.status_code != 200:
                    raise MetadataError(UPSTREAM_ERROR, f"ToolNet failed ({resp.status_code}).")
                try:
                    _, content, usage = parse_chat_body(resp.text)
                except MetadataError:
                    raise
                except Exception:
                    raise MetadataError(INVALID_RESPONSE, "ToolNet response has no usable content.")
                data = extract_json_object(content if isinstance(content, str) else "")
                title, description, hashtags = validate_metadata(data, context_empty=context_empty)
                latency = round(time.monotonic() - started, 1)
                logger.info(
                    "metadata generated reel=%s model=%s latency=%ss", reel_id, self.config.model, latency
                )
                actual = usage.get("total_tokens") if isinstance(usage, dict) else None
                await limiter.settle(estimate, int(actual) if isinstance(actual, (int, float)) else None)
                settled = True
                return GeneratedMetadata(
                    title=title, description=description, hashtags=hashtags,
                    model=self.config.model, usage=usage if isinstance(usage, dict) else {},
                )
        finally:
            if not settled:
                await limiter.release(estimate)
        assert last_error is not None
        raise last_error


@dataclass
class EnsureMetadataResult:
    metadata: GeneratedMetadata
    cached: bool
    model: str
    usage: dict


async def ensure_ai_metadata(
    reel: dict,
    *,
    pipeline_id: str | None = None,
    transport=None,
) -> EnsureMetadataResult:
    """Shared path for manual API and publish worker: cache-first, else 1 ToolNet call.

    Raises MetadataError (incl. TOOLNET_CONFIG_MISSING when AI is off, or AI_DISABLED_FOR_PIPELINE).
    Persists generated rows; never touches facebook_reels.caption.
    """
    from ..db.repositories import ai_metadata, ai_settings, reels
    from ..db.repositories.ai_metadata import source_hash

    reel_db_id = reel["id"]
    target_pipeline_id = pipeline_id or reel.get("pipeline_id")
    if not target_pipeline_id and reel.get("source_id"):
        target_pipeline_id = await reels.get_reel_pipeline_id(reel_db_id)

    from ..config import settings as app_settings

    if target_pipeline_id:
        # No forced model: the pipeline's stored choice wins, else global.
        pipeline_settings, config_hash = await ai_settings.current_config_hash(
            target_pipeline_id
        )
    else:
        pipeline_settings = ai_settings.default_settings("default")
        config_hash = ai_settings.compute_config_hash(
            enabled=pipeline_settings["enabled"],
            system_prompt=pipeline_settings.get("system_prompt"),
            title_template=pipeline_settings.get("title_template"),
            description_template=pipeline_settings.get("description_template"),
            locked_hashtags=pipeline_settings.get("locked_hashtags"),
            language=pipeline_settings.get("language"),
            model=None,
        )
    model = (
        pipeline_settings.get("model") or app_settings.TOOLNET_MODEL or ""
    ).strip()
    generator = FacebookMetadataGenerator.from_settings(transport=transport, model=model or None)

    if not pipeline_settings.get("enabled", True):
        raise MetadataError(
            AI_DISABLED_FOR_PIPELINE,
            f"AI processing is disabled for pipeline {target_pipeline_id or 'default'}.",
        )

    # config_hash is already canonical (recomputed, never the stored
    # legacy hash) from the branch above.
    if not await ai_metadata.needs_generation(
        reel_db_id, reel.get("caption"), model, reel.get("reel_id"), config_hash=config_hash
    ):
        row = await ai_metadata.get_for_reel(reel_db_id)
        assert row is not None
        return EnsureMetadataResult(
            metadata=GeneratedMetadata(
                title=row.get("title") or "",
                description=row.get("description") or "",
                hashtags=row.get("hashtags", []),
                model=row.get("model") or model,
                usage={},
            ),
            cached=True,
            model=row.get("model") or model,
            usage={},
        )

    generator.custom_system_prompt = pipeline_settings.get("system_prompt") or ""
    generator.language = pipeline_settings.get("language") or "vi"

    generated = await generator.generate(
        reel.get("reel_id") or reel_db_id,
        reel.get("caption"),
        reel.get("reel_url"),
    )

    final_title = apply_title_template(pipeline_settings.get("title_template"), generated.title)
    final_hashtags = apply_locked_hashtags(pipeline_settings.get("locked_hashtags"), generated.hashtags)
    final_description = apply_description_template(
        pipeline_settings.get("description_template"),
        generated.description,
        final_hashtags,
        reel.get("reel_url"),
    )

    final_metadata = GeneratedMetadata(
        title=final_title,
        description=final_description,
        hashtags=final_hashtags,
        model=generated.model,
        usage=generated.usage,
    )

    await ai_metadata.upsert_generated(
        reel_db_id=reel_db_id,
        title=final_title,
        description=final_description,
        hashtags=final_hashtags,
        model=generated.model,
        source_hash=source_hash(reel.get("caption"), reel.get("reel_id")),
        config_hash=config_hash,
    )
    return EnsureMetadataResult(
        metadata=final_metadata, cached=False, model=final_metadata.model, usage=final_metadata.usage
    )
