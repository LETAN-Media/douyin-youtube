import asyncio
import json
import os
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import app.db.client as client_module
from app.config import settings
from app.db.client import migrate
from app.db.repositories import ai_metadata, pipelines, reels, sources
from app.main import create_app
from app.services.facebook_ai_metadata import (
    FacebookMetadataGenerator,
    MetadataError,
    ToolNetConfig,
    extract_json_object,
    validate_metadata,
)

TEST_DB_PATH = Path("/tmp/backend_facebook_task8a_test.db")
TEST_DB_URL = f"file:{TEST_DB_PATH}"
ADMIN = "test_admin_token"
AUTH_HEADERS = {"X-Admin-Token": ADMIN}

GOOD_JSON = {
    "title": "Khoảnh khắc vui nhộn khiến ai cũng bật cười",
    "description": "Một đoạn reel ngắn ghi lại khoảnh khắc vui vẻ.",
    "hashtags": ["#vuinhon", "#giaitri", "#reels"],
}


def make_completion(content: str, usage: dict | None = None) -> dict:
    return {
        "id": "chatcmpl-x",
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }


def fresh_db() -> None:
    client_module._client = None
    os.environ["ADMIN_TOKEN"] = ADMIN
    os.environ["TURSO_DATABASE_URL"] = TEST_DB_URL
    os.environ["TURSO_AUTH_TOKEN"] = "test_token"
    settings.ADMIN_TOKEN = ADMIN
    settings.TURSO_DATABASE_URL = TEST_DB_URL
    settings.TURSO_AUTH_TOKEN = "test_token"
    settings.TOOLNET_BASE_URL = "https://toolnet.example.com/v1"
    settings.TOOLNET_API_KEY = "test_toolnet_key"
    settings.TOOLNET_MODEL = "groq/qwen/qwen3.8-27b"
    settings.TOOLNET_AI_ENABLED = True
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    for suffix in ("-wal", "-shm", "-journal"):
        p = Path(str(TEST_DB_PATH) + suffix)
        if p.exists():
            p.unlink()
    asyncio.run(migrate())


@pytest.fixture(autouse=True)
def _reset_limiter():
    from app.services import ai_rate_limit

    ai_rate_limit.reset_shared_limiter()
    yield
    ai_rate_limit.reset_shared_limiter()


@pytest.fixture()
def db():
    prev = {
        "url": os.environ.get("TURSO_DATABASE_URL"),
        "admin": os.environ.get("ADMIN_TOKEN"),
        "settings_url": settings.TURSO_DATABASE_URL,
        "base": settings.TOOLNET_BASE_URL,
        "key": settings.TOOLNET_API_KEY,
        "model": settings.TOOLNET_MODEL,
        "enabled": settings.TOOLNET_AI_ENABLED,
    }
    fresh_db()
    yield
    client_module._client = None
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    if prev["url"] is not None:
        os.environ["TURSO_DATABASE_URL"] = prev["url"]
    if prev["admin"] is not None:
        os.environ["ADMIN_TOKEN"] = prev["admin"]
    settings.TURSO_DATABASE_URL = prev["settings_url"]
    settings.TOOLNET_BASE_URL = prev["base"]
    settings.TOOLNET_API_KEY = prev["key"]
    settings.TOOLNET_MODEL = prev["model"]
    settings.TOOLNET_AI_ENABLED = prev["enabled"]
    client_module._client = None


def seed_reel(rid="r1", caption="Một chú mèo con chơi bóng len rất vui"):
    async def _go():
        await pipelines.create_pipeline(pipeline_id="pl_ai", name="AI", slug="pl_ai")
        try:
            await sources.create_source(
                source_id="pl_ai_src", pipeline_id="pl_ai", page_id="111",
                reels_url="https://www.facebook.com/111/reels/",
            )
        except Exception:
            pass
        await reels.insert_reel_if_new(
            reel_db_id=f"pl_ai_{rid}", source_id="pl_ai_src", reel_id=rid,
            reel_url=f"https://www.facebook.com/reel/{rid}/", caption=caption,
        )

    asyncio.run(_go())
    return f"pl_ai_{rid}"


def gen_with(transport, **over) -> FacebookMetadataGenerator:
    cfg = ToolNetConfig(
        base_url="https://toolnet.example.com/v1",
        api_key="test_toolnet_key",
        model="groq/qwen/qwen3.8-27b",
        **over,
    )
    return FacebookMetadataGenerator(cfg, transport=transport)


def transport_for(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


# ---------- config ----------


def test_config_missing(db) -> None:
    settings.TOOLNET_API_KEY = None
    with pytest.raises(MetadataError) as exc:
        FacebookMetadataGenerator.from_settings()
    assert exc.value.code == "TOOLNET_CONFIG_MISSING"


def test_config_disabled(db) -> None:
    settings.TOOLNET_AI_ENABLED = False
    with pytest.raises(MetadataError) as exc:
        FacebookMetadataGenerator.from_settings()
    assert exc.value.code == "TOOLNET_CONFIG_MISSING"


# ---------- parsing / validation ----------


def test_success_json(db) -> None:
    t = transport_for(lambda req: httpx.Response(200, json=make_completion(json.dumps(GOOD_JSON))))
    out = asyncio.run(gen_with(t).generate("r1", "caption"))
    assert out.title == GOOD_JSON["title"]
    assert out.hashtags == GOOD_JSON["hashtags"]
    assert out.model == "groq/qwen/qwen3.8-27b"


def test_code_fence_json(db) -> None:
    body = "```json\n" + json.dumps(GOOD_JSON) + "\n```"
    t = transport_for(lambda req: httpx.Response(200, json=make_completion(body)))
    out = asyncio.run(gen_with(t).generate("r1", "caption"))
    assert out.title == GOOD_JSON["title"]


def test_invalid_json(db) -> None:
    t = transport_for(lambda req: httpx.Response(200, json=make_completion("xin chào, không phải json")))
    with pytest.raises(MetadataError) as exc:
        asyncio.run(gen_with(t).generate("r1", "caption"))
    assert exc.value.code == "AI_INVALID_RESPONSE"


def test_missing_title(db) -> None:
    bad = dict(GOOD_JSON, title="  ")
    t = transport_for(lambda req: httpx.Response(200, json=make_completion(json.dumps(bad))))
    with pytest.raises(MetadataError) as exc:
        asyncio.run(gen_with(t).generate("r1", "caption"))
    assert exc.value.code == "AI_INVALID_RESPONSE"


def test_long_title_truncated(db) -> None:
    bad = dict(GOOD_JSON, title="x" * 150)
    title, _, _ = validate_metadata(bad)
    assert len(title) == 100


def test_hashtags_normalization(db) -> None:
    data = dict(GOOD_JSON, hashtags=["vuinhon", "# giaitri ", "#reels", "#reels", 123])
    _, _, tags = validate_metadata(data)
    assert tags[0] == "#vuinhon" and len(tags) <= 6
    with pytest.raises(MetadataError):
        validate_metadata(dict(GOOD_JSON, hashtags=["#a"]))


def test_empty_caption_uses_fallback(db) -> None:
    seen: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(req.content.decode())
        return httpx.Response(200, json=make_completion(json.dumps(GOOD_JSON)))

    t = transport_for(handler)
    asyncio.run(gen_with(t).generate("r1", "  "))
    user_msg = seen["body"]["messages"][1]["content"]
    assert "trung tính" in user_msg or "Facebook Reel" in user_msg


def test_empty_caption_bad_output_is_insufficient(db) -> None:
    t = transport_for(lambda req: httpx.Response(200, json=make_completion(json.dumps({"title": ""}))))
    with pytest.raises(MetadataError) as exc:
        asyncio.run(gen_with(t).generate("r1", ""))
    assert exc.value.code == "AI_INSUFFICIENT_CONTEXT"


def test_extract_json_object_helpers(db) -> None:
    assert extract_json_object('{"a": 1} extra') == {"a": 1}
    with pytest.raises(MetadataError):
        extract_json_object("no json here")


# ---------- HTTP errors ----------


def test_401(db) -> None:
    t = transport_for(lambda req: httpx.Response(401, json={"error": "bad key"}))
    with pytest.raises(MetadataError) as exc:
        asyncio.run(gen_with(t).generate("r1", "caption"))
    assert exc.value.code == "TOOLNET_AUTH_FAILED"


def test_429_retries_then_surfaces(db) -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, json={"error": "busy"})

    with pytest.raises(MetadataError) as exc:
        asyncio.run(gen_with(t := transport_for(handler)).generate("r1", "caption"))
    assert exc.value.code == "TOOLNET_RATE_LIMITED"
    assert calls["n"] == 3  # initial + 2 retries


def test_500_retries(db) -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(500, json={"error": "boom"})
        return httpx.Response(200, json=make_completion(json.dumps(GOOD_JSON)))

    out = asyncio.run(gen_with(transport_for(handler)).generate("r1", "caption"))
    assert out.title == GOOD_JSON["title"] and calls["n"] == 3


def test_timeout(db) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    with pytest.raises(MetadataError) as exc:
        asyncio.run(gen_with(transport_for(handler), timeout=5).generate("r1", "caption"))
    assert exc.value.code == "TOOLNET_TIMEOUT"


def test_no_key_leak(db) -> None:
    t = transport_for(lambda req: httpx.Response(401, json={"error": "bad"}))
    try:
        asyncio.run(gen_with(t).generate("r1", "caption"))
        raise AssertionError("should raise")
    except MetadataError as exc:
        assert "test_toolnet_key" not in str(exc) and "test_toolnet_key" not in exc.code


# ---------- persistence / cache ----------


class FakeGenerator:
    """Route-level fake: generate() without network."""

    def __init__(self, transport):
        self._transport = transport
        self.config = ToolNetConfig(
            base_url="https://toolnet.example.com/v1",
            api_key="test_toolnet_key",
            model="groq/qwen/qwen3.8-27b",
        )

    async def generate(self, reel_id, caption, reel_url=None):
        real = FacebookMetadataGenerator(self.config, transport=self._transport)
        return await real.generate(reel_id, caption, reel_url)


def _run_generate(reel_db_id: str, transport, monkeypatch) -> tuple[int, dict]:
    import app.routes.ai_metadata as route_mod
    from fastapi.testclient import TestClient
    from app.main import create_app

    fake = FakeGenerator(transport)
    monkeypatch.setattr(
        route_mod, "FacebookMetadataGenerator",
        type("FG", (), {"from_settings": staticmethod(lambda transport=None: fake)}),
    )
    client = TestClient(create_app())
    r = client.post(f"/api/facebook/reels/{reel_db_id}/ai-metadata/generate", headers=AUTH_HEADERS)
    return r.status_code, r.json()


def test_cache_hit(db, monkeypatch) -> None:
    rid = seed_reel()
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=make_completion(json.dumps(GOOD_JSON)))

    t = transport_for(handler)
    s1, b1 = _run_generate(rid, t, monkeypatch)
    assert s1 == 200 and b1["cached"] is False
    s2, b2 = _run_generate(rid, t, monkeypatch)
    assert s2 == 200 and b2["cached"] is True
    assert calls["n"] == 1  # second call reused Turso row
    assert b2["metadata"]["title"] == GOOD_JSON["title"]


def test_caption_changed_regenerates(db, monkeypatch) -> None:
    rid = seed_reel()
    t = transport_for(lambda req: httpx.Response(200, json=make_completion(json.dumps(GOOD_JSON))))
    _run_generate(rid, t, monkeypatch)

    async def _change():
        from app.db.client import get_client

        await get_client().execute(
            "UPDATE facebook_reels SET caption = :c WHERE id = :id",
            {"c": "Một chú chó con hoàn toàn khác", "id": rid},
        )

    asyncio.run(_change())
    assert asyncio.run(ai_metadata.needs_generation(rid, "Một chú chó con hoàn toàn khác", "groq/qwen/qwen3.8-27b", "r1")) is True


def test_model_changed_regenerates(db, monkeypatch) -> None:
    rid = seed_reel()
    t = transport_for(lambda req: httpx.Response(200, json=make_completion(json.dumps(GOOD_JSON))))
    _run_generate(rid, t, monkeypatch)
    assert asyncio.run(ai_metadata.needs_generation(rid, "Một chú mèo con chơi bóng len rất vui", "other-model", "r1")) is True
    assert asyncio.run(ai_metadata.needs_generation(rid, "Một chú mèo con chơi bóng len rất vui", "groq/qwen/qwen3.8-27b", "r1")) is False


def test_caption_preserved(db, monkeypatch) -> None:
    rid = seed_reel()
    t = transport_for(lambda req: httpx.Response(200, json=make_completion(json.dumps(GOOD_JSON))))
    _run_generate(rid, t, monkeypatch)

    async def _get():
        from app.db.repositories import reels

        return await reels.get_reel(rid)

    row = asyncio.run(_get())
    assert row["caption"] == "Một chú mèo con chơi bóng len rất vui"


def test_endpoint_auth_and_get(db) -> None:
    from fastapi.testclient import TestClient
    from app.main import create_app

    client = TestClient(create_app())
    r = client.post("/api/facebook/reels/xxx/ai-metadata/generate")
    assert r.status_code == 401
    r = client.post("/api/facebook/reels/xxx/ai-metadata/generate", headers=AUTH_HEADERS)
    assert r.status_code == 404
    r = client.get("/api/facebook/reels/xxx/ai-metadata", headers=AUTH_HEADERS)
    assert r.status_code == 404


def test_stats_endpoint(db, monkeypatch) -> None:
    rid = seed_reel()
    t = transport_for(lambda req: httpx.Response(200, json=make_completion(json.dumps(GOOD_JSON))))
    _run_generate(rid, t, monkeypatch)
    from fastapi.testclient import TestClient
    from app.main import create_app

    client = TestClient(create_app())
    r = client.get("/api/facebook/pipelines/pl_ai/ai-metadata/stats", headers=AUTH_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["generated"] == 1 and body["pending"] == 0


def test_failed_status_persisted(db, monkeypatch) -> None:
    rid = seed_reel()
    t = transport_for(lambda req: httpx.Response(500, json={"error": "boom"}))
    s, b = _run_generate(rid, t, monkeypatch)
    assert s == 502 and b["error"] == "TOOLNET_UPSTREAM_ERROR"
    row = asyncio.run(ai_metadata.get_for_reel(rid))
    assert row is not None and row["status"] == "failed"


def test_migration_idempotent(db) -> None:
    asyncio.run(migrate())
    asyncio.run(migrate())
    row = asyncio.run(ai_metadata.get_for_reel("nope"))
    assert row is None


def test_source_hash_includes_reel_id(db) -> None:
    from app.db.repositories.ai_metadata import source_hash

    assert source_hash("cap", "r1") != source_hash("cap", "r2")
    assert source_hash("cap", "r1") == source_hash("cap", "r1")
    assert source_hash("cap", None) != source_hash("cap", "r1")


def test_legacy_column_renamed(db) -> None:
    async def _go():
        from app.db.client import get_client

        client = get_client()
        await client.execute("DROP TABLE IF EXISTS facebook_ai_metadata")
        await client.execute(
            "CREATE TABLE facebook_ai_metadata (reel_db_id TEXT PRIMARY KEY, source_caption_hash TEXT)"
        )
        from app.db.client import migrate as _migrate

        await _migrate()
        cols = await client.execute("PRAGMA table_info(facebook_ai_metadata)")
        names = [row[1] for row in (cols.rows or [])]
        return names

    names = asyncio.run(_go())
    assert "source_hash" in names
    assert "source_caption_hash" not in names


def test_sse_trailer_body_parsed(db) -> None:
    from app.services.facebook_ai_metadata import parse_chat_body

    raw = json.dumps(make_completion(json.dumps(GOOD_JSON))) + "\ndata: [DONE]\n\n"
    body, content, usage = parse_chat_body(raw)
    assert body["choices"][0]["message"]["content"]
    assert usage.get("total_tokens") == 30
    with pytest.raises(MetadataError):
        parse_chat_body("data: [DONE]\n\n")


def test_generate_with_sse_trailer(db) -> None:
    raw = json.dumps(make_completion(json.dumps(GOOD_JSON))) + "\ndata: [DONE]\n\n"

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=raw)

    out = asyncio.run(gen_with(transport_for(handler)).generate("r1", "caption"))
    assert out.title == GOOD_JSON["title"]


# ---------- local rate limiter ----------


def test_limiter_request_cap() -> None:
    from app.services.ai_rate_limit import AiRateLimiter, RateLimitExceeded

    now = [1000.0]
    lim = AiRateLimiter(2, 100000, clock=lambda: now[0])
    asyncio.run(lim.reserve(10))
    asyncio.run(lim.reserve(10))
    try:
        asyncio.run(lim.reserve(10))
        raise AssertionError("should raise")
    except RateLimitExceeded as e:
        assert e.retry_after_s > 0
    now[0] += 61.0
    asyncio.run(lim.reserve(10))  # window slid


def test_limiter_token_cap_and_settle() -> None:
    from app.services.ai_rate_limit import AiRateLimiter, RateLimitExceeded

    now = [1000.0]
    lim = AiRateLimiter(30, 100, clock=lambda: now[0])
    asyncio.run(lim.reserve(90))
    try:
        asyncio.run(lim.reserve(20))
        raise AssertionError("should raise")
    except RateLimitExceeded:
        pass
    asyncio.run(lim.settle(90, 40))  # actual usage smaller
    asyncio.run(lim.reserve(20))  # fits now
    asyncio.run(lim.release(20))
    snap = lim.snapshot()
    assert snap["tokens_used"] == 40


def test_generate_blocked_by_local_limit(db, monkeypatch) -> None:
    from app.services import ai_rate_limit

    monkeypatch.setattr(settings, "TOOLNET_MAX_REQUESTS_PER_MINUTE", 1)
    monkeypatch.setattr(settings, "TOOLNET_MAX_TOKENS_PER_MINUTE", 8000)
    ai_rate_limit.reset_shared_limiter()
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=make_completion(json.dumps(GOOD_JSON)))

    t = transport_for(handler)
    asyncio.run(gen_with(t).generate("r1", "caption one"))
    with pytest.raises(MetadataError) as exc:
        asyncio.run(gen_with(t).generate("r2", "caption two"))
    assert exc.value.code == "TOOLNET_RATE_LIMITED"
    assert calls["n"] == 1  # second call never hit the provider
    ai_rate_limit.reset_shared_limiter()


def test_generate_records_actual_usage(db, monkeypatch) -> None:
    from app.services import ai_rate_limit

    monkeypatch.setattr(settings, "TOOLNET_MAX_REQUESTS_PER_MINUTE", 30)
    monkeypatch.setattr(settings, "TOOLNET_MAX_TOKENS_PER_MINUTE", 100000)
    ai_rate_limit.reset_shared_limiter()
    t = transport_for(lambda req: httpx.Response(200, json=make_completion(json.dumps(GOOD_JSON))))
    asyncio.run(gen_with(t).generate("r1", "caption"))
    lim = ai_rate_limit.get_shared_limiter(30, 100000)
    assert lim.snapshot()["tokens_used"] == 30  # actual usage, not estimate
    ai_rate_limit.reset_shared_limiter()
