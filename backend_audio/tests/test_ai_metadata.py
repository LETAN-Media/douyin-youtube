import json
import httpx
import pytest

from app.services import ai_metadata as ai
from app.db.repositories.audio import _parse_genre


def test_parse_chat_body_standard():
    raw = json.dumps({
        "choices": [{"message": {"content": "{\"title\": \"T\", \"description\": \"D\", \"hashtags\": [\"#A\", \"#B\", \"#C\"]}"}}],
        "usage": {"total_tokens": 10}
    })
    body, content, usage = ai.parse_chat_body(raw)
    assert "choices" in body
    assert "title" in content
    assert usage.get("total_tokens") == 10


def test_parse_chat_body_toolnet_trailing_done():
    # Production ToolNet response format: valid JSON followed by data: [DONE]
    raw = (
        '{"id":"chatcmpl-123","object":"chat.completion","created":1792619461,"model":"qwen/qwen3.8-27b",'
        '"choices":[{"index":0,"message":{"role":"assistant","content":"{\\"title\\": \\"Audio Hay\\", \\"description\\": \\"Mo ta\\", \\"hashtags\\": [\\"#A\\", \\"#B\\", \\"#C\\"]}"},'
        '"logprobs":null,"finish_reason":"stop"}],"usage":{"total_tokens":42}}\n'
        'data: [DONE]\n\n'
    )
    body, content, usage = ai.parse_chat_body(raw)
    assert body["model"] == "qwen/qwen3.8-27b"
    assert "Audio Hay" in content
    assert usage["total_tokens"] == 42


@pytest.mark.asyncio
async def test_generate_metadata_with_mock_toolnet(monkeypatch):
    import os
    monkeypatch.setenv("TOOLNET_BASE_URL", "https://api.toolnet.tech/v1")
    monkeypatch.setenv("TOOLNET_API_KEY", "test_key")
    monkeypatch.setenv("TOOLNET_MODEL", "groq/qwen/qwen3.8-27b")
    monkeypatch.setenv("TOOLNET_AI_ENABLED", "true")

    toolnet_response = (
        '{"id":"chatcmpl-mock","choices":[{"message":{"content":"{\\"title\\": \\"Audio Truyện Hot\\", \\"description\\": \\"Truyện audio hay\\", \\"hashtags\\": [\\"#AudioHay\\", \\"#NgonTinh\\", \\"#DocTruyen\\"]}"}}],'
        '"usage":{"total_tokens":50}}\ndata: [DONE]\n\n'
    )

    async def fake_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=toolnet_response, request=request)

    transport = httpx.MockTransport(fake_handler)

    ctx = ai.AiContext(
        genre=["Audio Ngôn Tình"],
        source_title="Nguồn truyện 1",
        channel_name="Kênh Audio",
    )
    settings_row = {
        "enabled": True,
        "language": "vi",
        "generate_title": True,
        "generate_description": True,
        "generate_hashtags": True,
        "title_template": "{TITLE} | AUDIO",
        "description_template": "{hashtags}",
        "locked_hashtags_json": '["#audiotruyen"]',
    }

    meta = await ai.generate_metadata(ctx, settings_row, transport=transport)
    assert meta.title == "Audio Truyện Hot | AUDIO"
    assert "#audiotruyen" in meta.hashtags
    assert "#AudioHay" in meta.hashtags
    assert meta.model == "groq/qwen/qwen3.8-27b"


@pytest.mark.asyncio
async def test_generate_metadata_falls_back_to_secondary_model(monkeypatch):
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "TOOLNET_BASE_URL", "https://api.toolnet.tech/v1")
    monkeypatch.setattr(app_settings, "TOOLNET_API_KEY", "test_key")
    monkeypatch.setattr(app_settings, "TOOLNET_MODEL", "primary/model")
    monkeypatch.setattr(app_settings, "TOOLNET_FALLBACK_MODEL",
                        "agnes/agnes-3.0-flash")
    monkeypatch.setattr(app_settings, "TOOLNET_AI_ENABLED", True)

    fallback_response = (
        '{"id":"chatcmpl-mock","choices":[{"message":{"content":"{\\"title\\": \\"Audio Fallback\\", \\"description\\": \\"Mo ta\\", \\"hashtags\\": [\\"#A\\", \\"#B\\", \\"#C\\"]}"}}],'
        '"usage":{"total_tokens":50}}\ndata: [DONE]\n\n'
    )
    seen_models = []

    async def fake_handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        seen_models.append(model)
        if model == "primary/model":
            return httpx.Response(500, text="upstream down", request=request)
        return httpx.Response(200, text=fallback_response, request=request)

    ctx = ai.AiContext(source_title="Nguồn truyện 1")
    settings_row = {
        "enabled": True,
        "language": "vi",
        "generate_title": True,
        "generate_description": True,
        "generate_hashtags": True,
    }

    meta = await ai.generate_metadata(ctx, settings_row,
                                      transport=httpx.MockTransport(fake_handler))

    assert meta.model == "agnes/agnes-3.0-flash"
    assert meta.title == "Audio Fallback"
    assert seen_models == ["primary/model"] * (ai.MAX_RETRIES + 1) + [
        "agnes/agnes-3.0-flash"]


def test_parse_genre_nested_and_corrupted():
    # Normal list
    assert _parse_genre(["Audio Ngôn Tình", "Audio Tổng Tài"]) == ["Audio Ngôn Tình", "Audio Tổng Tài"]

    # JSON string
    assert _parse_genre('["Audio Tâm Lý", "Audio Kinh Dị"]') == ["Audio Tâm Lý", "Audio Kinh Dị"]

    # Plain string
    assert _parse_genre("Audio Trinh Thám") == ["Audio Trinh Thám"]

    # Corrupted multi-escaped JSON string (like production before fix)
    corrupted = "['[\\'[\\\\\\'[\\\\\\\\\\\\\\'[\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\'[\"[\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\'Audio Ngôn Tình\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\', \\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\'Audio Tổng Tài\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\']\", \\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\'Audio Ngôn Tình\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\', \\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\'Audio Tâm Lý\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\', \\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\'Audio Tổng Tài\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\']\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\']\\\\\\\\\\\\\\']\\\\\\']\\']']"
    unwrapped = _parse_genre(corrupted)
    assert isinstance(unwrapped, list)
    for g in unwrapped:
        assert not g.startswith("[")
        assert not g.endswith("]")
