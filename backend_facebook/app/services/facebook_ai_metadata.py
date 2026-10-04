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

logger = logging.getLogger("backend-facebook.ai-metadata")

CONFIG_MISSING = "TOOLNET_CONFIG_MISSING"
AUTH_FAILED = "TOOLNET_AUTH_FAILED"
RATE_LIMITED = "TOOLNET_RATE_LIMITED"
TIMEOUT = "TOOLNET_TIMEOUT"
UPSTREAM_ERROR = "TOOLNET_UPSTREAM_ERROR"
INVALID_RESPONSE = "AI_INVALID_RESPONSE"
INSUFFICIENT_CONTEXT = "AI_INSUFFICIENT_CONTEXT"

MAX_RETRIES = 2
FALLBACK_CONTEXT = (
    "Đây là một Facebook Reel. Hãy tạo metadata trung tính dựa trên thông tin có sẵn."
)

SYSTEM_PROMPT = """Bạn viết metadata YouTube bằng TIẾNG VIỆT cho một Facebook Reel.
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
    ) -> None:
        if not config.api_key:
            raise MetadataError(CONFIG_MISSING, "TOOLNET_API_KEY is not configured.")
        self.config = config
        self._transport = transport

    @classmethod
    def from_settings(
        cls, transport: httpx.AsyncBaseTransport | None = None
    ) -> "FacebookMetadataGenerator":
        from ..config import settings

        try:
            base_url, api_key, model = settings.require_toolnet()
        except RuntimeError as exc:
            raise MetadataError(CONFIG_MISSING, str(exc))
        return cls(
            ToolNetConfig(
                base_url=base_url, api_key=api_key, model=model,
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
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.3,
            "max_tokens": 800,
        }

        last_error: MetadataError | None = None
        started = time.monotonic()
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
            return GeneratedMetadata(
                title=title, description=description, hashtags=hashtags,
                model=self.config.model, usage=usage if isinstance(usage, dict) else {},
            )
        assert last_error is not None
        raise last_error
