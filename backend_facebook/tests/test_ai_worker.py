"""Regression tests for the AI metadata background worker (Task 13).

Covers the production stall of pipeline CHANG HIU TV:
- worker crashed with AttributeError (repo has get_for_reel, services
  called a non-existent get_metadata), so no reel was ever processed;
- config_hash computed without the ToolNet model never matched the
  scheduler's hash, so generated rows were never AI-ready.

No real ToolNet calls: httpx.MockTransport serves canned completions.
No YouTube, no scheduler, no publisher involved.
"""

import asyncio
import json
import os
from pathlib import Path

import httpx

import app.db.client as client_module
from app.config import settings
from app.db.client import migrate
from app.db.repositories import ai_metadata, ai_settings, pipelines, reels, sources
from app.services.facebook_ai_worker import get_ai_worker_status, run_ai_worker_once

TEST_DB_PATH = Path("/tmp/backend_facebook_ai_worker_test.db")
TEST_DB_URL = f"file:{TEST_DB_PATH}"
ADMIN = "test_admin_token"

GOOD_JSON = {
    "title": "Khoảnh khắc vui nhộn khiến ai cũng bật cười",
    "description": "Một đoạn reel ngắn ghi lại khoảnh khắc vui vẻ.",
    "hashtags": ["#vuinhon", "#giaitri", "#reels"],
}


def make_completion(content: str) -> dict:
    return {
        "id": "chatcmpl-x",
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }


def mock_transport() -> httpx.MockTransport:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_completion(json.dumps(GOOD_JSON)))

    return httpx.MockTransport(handler)


_PREV_SETTINGS: dict = {}
_PREV_ENV: dict = {}


def setup_function(_func=None) -> None:
    _PREV_SETTINGS.clear()
    _PREV_ENV.clear()
    for key in (
        "ADMIN_TOKEN", "TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN",
        "TOOLNET_BASE_URL", "TOOLNET_API_KEY", "TOOLNET_MODEL", "TOOLNET_AI_ENABLED",
    ):
        _PREV_SETTINGS[key] = getattr(settings, key)
        _PREV_ENV[key] = os.environ.get(key)
    client_module._client = None
    os.environ["ADMIN_TOKEN"] = ADMIN
    os.environ["TURSO_DATABASE_URL"] = TEST_DB_URL
    os.environ["TURSO_AUTH_TOKEN"] = "test_token"
    settings.ADMIN_TOKEN = ADMIN
    settings.TURSO_DATABASE_URL = TEST_DB_URL
    settings.TURSO_AUTH_TOKEN = "test_token"
    settings.TOOLNET_BASE_URL = "https://toolnet.example.com/v1"
    settings.TOOLNET_API_KEY = "test_toolnet_key"
    settings.TOOLNET_MODEL = "test-model-v1"
    settings.TOOLNET_AI_ENABLED = True
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    for suffix in ("-wal", "-shm", "-journal"):
        p = Path(str(TEST_DB_PATH) + suffix)
        if p.exists():
            p.unlink()
    asyncio.run(migrate())


def teardown_function(_func=None) -> None:
    # Drop the client BEFORE unlinking so later test files that rely on
    # os.environ.setdefault (e.g. test_database.py) get a clean slate.
    client_module._client = None
    for key, value in _PREV_SETTINGS.items():
        setattr(settings, key, value)
    for key, value in _PREV_ENV.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    _PREV_SETTINGS.clear()
    _PREV_ENV.clear()
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    for suffix in ("-wal", "-shm", "-journal"):
        p = Path(str(TEST_DB_PATH) + suffix)
        if p.exists():
            p.unlink()


def seed_pipeline(pipe_id: str = "pl_w1") -> None:
    async def _go():
        await pipelines.create_pipeline(pipeline_id=pipe_id, name="W", slug=pipe_id)
        try:
            await sources.create_source(
                source_id=f"{pipe_id}_src", pipeline_id=pipe_id, page_id="111",
                reels_url="https://www.facebook.com/111/reels/",
            )
        except Exception:
            pass

    asyncio.run(_go())


def seed_reel(pipe_id: str = "pl_w1", rid: str = "r1", caption: str = "Một chú mèo con chơi bóng len rất vui") -> str:
    reel_db_id = f"{pipe_id}_{rid}"

    async def _go():
        await reels.insert_reel_if_new(
            reel_db_id=reel_db_id, source_id=f"{pipe_id}_src", reel_id=rid,
            reel_url=f"https://www.facebook.com/reel/{rid}/", caption=caption,
        )

    asyncio.run(_go())
    return reel_db_id


def scheduler_hash() -> str:
    """Hash exactly the way the scheduler computes it."""
    return ai_settings.compute_config_hash(
        enabled=True,
        system_prompt="",
        title_template="{title}",
        description_template="{description}\n\n{hashtags}",
        locked_hashtags=[],
        language="vi",
        model=settings.TOOLNET_MODEL,
    )


def test_worker_once_generates_and_becomes_ai_ready() -> None:
    """New reel -> worker one-shot -> generated row -> AI-ready for scheduler."""
    seed_pipeline()
    reel_db_id = seed_reel()

    result = asyncio.run(run_ai_worker_once(transport=mock_transport()))

    assert result is not None and result.get("status") == "generated", result
    assert result.get("reel_db_id") == reel_db_id

    async def _check():
        reel = await reels.get_reel(reel_db_id)
        assert reel is not None and reel["status"] == "new"
        row = await ai_metadata.get_for_reel(reel_db_id)
        assert row is not None and row["status"] == "generated"
        ready = await reels.list_ai_ready_reels("pl_w1", scheduler_hash())
        assert [r["id"] for r in ready] == [reel_db_id]

    asyncio.run(_check())


def test_worker_regenerates_stale_config_hash() -> None:
    """Production scenario: generated row under an old hash is regenerated
    and becomes AI-ready (no duplicate rows, no crash)."""
    seed_pipeline()
    reel_db_id = seed_reel(caption="Caption gốc cho video kiểm thử băm cấu hình")

    async def _seed_stale():
        await ai_metadata.upsert_generated(
            reel_db_id=reel_db_id,
            title="Tiêu đề cũ",
            description="Mô tả cũ",
            hashtags=["#cu", "#xua", "#reels"],
            model=settings.TOOLNET_MODEL,
            source_hash=ai_metadata.source_hash("Caption gốc cho video kiểm thử băm cấu hình", "r1"),
            config_hash="stale_hash_from_old_settings",
        )

    asyncio.run(_seed_stale())

    async def _not_ready_before():
        ready = await reels.list_ai_ready_reels("pl_w1", scheduler_hash())
        assert ready == []

    asyncio.run(_not_ready_before())

    result = asyncio.run(run_ai_worker_once(transport=mock_transport()))
    assert result is not None and result.get("status") == "generated", result

    async def _ready_after():
        row = await ai_metadata.get_for_reel(reel_db_id)
        assert row is not None and row["status"] == "generated"
        assert row.get("config_hash") == scheduler_hash()
        ready = await reels.list_ai_ready_reels("pl_w1", scheduler_hash())
        assert [r["id"] for r in ready] == [reel_db_id]

    asyncio.run(_ready_after())


def test_worker_status_does_not_crash() -> None:
    """get_ai_worker_status must not raise (previously called a missing
    get_global_stats repository function)."""
    seed_pipeline()
    seed_reel()

    status = asyncio.run(get_ai_worker_status())

    assert status["enabled"] is True
    assert status["concurrency"] == settings.FACEBOOK_AI_WORKER_CONCURRENCY
    assert status["global_queue"]["total_rows"] == 0

    asyncio.run(run_ai_worker_once(transport=mock_transport()))
    status2 = asyncio.run(get_ai_worker_status())
    assert status2["global_queue"]["generated"] == 1


def test_settings_saved_with_model_match_scheduler() -> None:
    """Settings saved through the (fixed) write path carry the real model
    in config_hash, so the scheduler sees rows as AI-ready."""
    seed_pipeline()

    async def _save():
        return await ai_settings.upsert_settings(
            pipeline_id="pl_w1",
            enabled=True,
            system_prompt="",
            title_template="{title}",
            description_template="{description}\n\n{hashtags}",
            locked_hashtags=[],
            language="vi",
            model=settings.TOOLNET_MODEL,
        )

    saved = asyncio.run(_save())
    assert saved.get("config_hash") == scheduler_hash()


def test_legacy_stored_hash_does_not_stall_worker() -> None:
    """Production scenario: a settings row saved by the old write path
    carries a model-less config_hash, and metadata rows were generated
    under it. The worker must ignore the stored hash, recompute the
    canonical one, regenerate, and make the reel AI-ready — otherwise
    the pipeline stalls silently with zero errors."""
    seed_pipeline()
    caption = "Caption gốc cho video kiểm thử hàm băm cũ"
    reel_db_id = seed_reel(caption=caption)

    stale_hash = ai_settings.compute_config_hash(
        enabled=True,
        system_prompt="",
        title_template="{title}",
        description_template="{description}\n\n{hashtags}",
        locked_hashtags=[],
        language="vi",
        model="",
    )
    assert stale_hash != scheduler_hash()

    async def _seed_legacy():
        # Old write path: settings saved without the model.
        await ai_settings.upsert_settings(
            pipeline_id="pl_w1",
            enabled=True,
            system_prompt="",
            title_template="{title}",
            description_template="{description}\n\n{hashtags}",
            locked_hashtags=[],
            language="vi",
            model=None,
        )
        stored, _canonical = await ai_settings.get_settings("pl_w1"), None
        assert stored.get("config_hash") == stale_hash
        # Old manual endpoint: row generated under the stored (stale) hash.
        await ai_metadata.upsert_generated(
            reel_db_id=reel_db_id,
            title="Tiêu đề cũ",
            description="Mô tả cũ",
            hashtags=["#cu", "#xua", "#reels"],
            model=settings.TOOLNET_MODEL,
            source_hash=ai_metadata.source_hash(caption, "r1"),
            config_hash=stale_hash,
        )

    asyncio.run(_seed_legacy())

    async def _not_ready_before():
        ready = await reels.list_ai_ready_reels("pl_w1", scheduler_hash())
        assert ready == []

    asyncio.run(_not_ready_before())

    result = asyncio.run(run_ai_worker_once(transport=mock_transport()))
    assert result is not None and result.get("status") == "generated", result

    async def _ready_after():
        row = await ai_metadata.get_for_reel(reel_db_id)
        assert row is not None and row["status"] == "generated"
        assert row.get("config_hash") == scheduler_hash()
        ready = await reels.list_ai_ready_reels("pl_w1", scheduler_hash())
        assert [r["id"] for r in ready] == [reel_db_id]

    asyncio.run(_ready_after())
