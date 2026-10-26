"""Tests for TikTok source resolution, source creation without ID, and pipeline-isolated AI Settings."""

import sys
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, patch

TEST_DB_PATH = Path("/tmp/tiktok_test.db")


def _reset_db() -> None:
    from app.db import client as db_client

    db_client._client = None
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.client import migrate
from app.services.tiktok_url import (
    clean_tiktok_username,
    resolve_tiktok_input,
)
from app.db.repositories import (
    pipelines as pipelines_repo,
    sources as sources_repo,
    ai_settings as ai_settings_repo,
)
from app.routes.sources import create_source
from app.routes.ai_metadata import (
    get_ai_settings,
    update_ai_settings,
    run_ai_test,
)
from app.services.tiktok_scan import scan_source
from app.services.tiktok_provider import ProviderError, TikTokProfile


@pytest.fixture(autouse=True)
async def setup_test_db():
    _reset_db()
    await migrate()
    yield
    _reset_db()



def test_clean_tiktok_username():
    assert clean_tiktok_username("@citrachoighelam_19") == "citrachoighelam_19"
    assert clean_tiktok_username("citrachoighelam_19") == "citrachoighelam_19"
    assert clean_tiktok_username("  citrachoighelam_19  ") == "citrachoighelam_19"
    assert (
        clean_tiktok_username("https://www.tiktok.com/@citrachoighelam_19")
        == "citrachoighelam_19"
    )
    assert (
        clean_tiktok_username("https://www.tiktok.com/@citrachoighelam_19?is_from_webapp=1")
        == "citrachoighelam_19"
    )
    assert (
        clean_tiktok_username("tiktok.com/@citrachoighelam_19")
        == "citrachoighelam_19"
    )
    assert (
        clean_tiktok_username("https://www.tiktok.com/@citrachoighelam_19/video/7698765134000295176")
        == "citrachoighelam_19"
    )
    assert clean_tiktok_username("") is None
    assert clean_tiktok_username("   ") is None


@pytest.mark.asyncio
async def test_resolve_tiktok_input():
    u, url = await resolve_tiktok_input("@citrachoighelam_19")
    assert u == "citrachoighelam_19"
    assert url == "https://www.tiktok.com/@citrachoighelam_19"

    u2, url2 = await resolve_tiktok_input("https://www.tiktok.com/@citrachoighelam_19?lang=vi")
    assert u2 == "citrachoighelam_19"
    assert url2 == "https://www.tiktok.com/@citrachoighelam_19"


@pytest.mark.asyncio
async def test_create_source_without_id_and_idempotent():
    pid = "test_pipeline_ai_1"
    await pipelines_repo.create_pipeline(pid, "AI Test Pipeline", "ai-test-pipeline")

    # 1. Create source without id (user only gives username)
    payload = {
        "pipeline_id": pid,
        "username": "@citrachoighelam_19",
    }
    src = await create_source(payload)
    assert src is not None
    assert src["id"].startswith("src_")
    assert src["username"] == "citrachoighelam_19"
    assert src["pipeline_id"] == pid
    assert src["source_url"] == "https://www.tiktok.com/@citrachoighelam_19"

    # 2. Idempotent check: creating the same source returns existing row
    src_dup = await create_source(payload)
    assert src_dup["id"] == src["id"]
    assert src_dup["username"] == src["username"]


@pytest.mark.asyncio
async def test_ai_settings_isolated_per_pipeline():
    pid_a = "pipe_ai_alpha"
    pid_b = "pipe_ai_beta"

    await pipelines_repo.create_pipeline(pid_a, "Pipeline Alpha", "pipe-alpha")
    await pipelines_repo.create_pipeline(pid_b, "Pipeline Beta", "pipe-beta")

    # Pipeline A settings
    await update_ai_settings(
        pid_a,
        {
            "model": "groq/openai/gpt-oss-120b",
            "system_prompt": "Phong cách năng động cho Pipeline Alpha",
            "tone": "humorous",
            "max_hashtags": 8,
            "locked_hashtags": ["#alpha", "#shorts"],
        },
    )

    # Pipeline B settings
    await update_ai_settings(
        pid_b,
        {
            "model": "openrouter/openai/gpt-4o-mini",
            "system_prompt": "Phong cách chuyên nghiệp cho Pipeline Beta",
            "tone": "professional",
            "max_hashtags": 12,
            "locked_hashtags": ["#beta", "#review"],
        },
    )

    cfg_a = await get_ai_settings(pid_a)
    cfg_b = await get_ai_settings(pid_b)

    assert cfg_a["system_prompt"] == "Phong cách năng động cho Pipeline Alpha"
    assert cfg_a["tone"] == "humorous"
    assert cfg_a["max_hashtags"] == 8
    assert "#alpha" in cfg_a["locked_hashtags"]

    assert cfg_b["system_prompt"] == "Phong cách chuyên nghiệp cho Pipeline Beta"
    assert cfg_b["tone"] == "professional"
    assert cfg_b["max_hashtags"] == 12
    assert "#beta" in cfg_b["locked_hashtags"]
    assert "#alpha" not in cfg_b["locked_hashtags"]


@pytest.mark.asyncio
async def test_ai_test_preview_endpoint():
    pid = "pipe_test_preview"
    await pipelines_repo.create_pipeline(pid, "Preview Pipe", "pipe-preview")

    with patch(
        "app.services.tiktok_ai_metadata._call_toolnet",
        new=AsyncMock(
            return_value={
                "title": "Mẹo chơi game cực đỉnh",
                "description": "Video hướng dẫn chi tiết cách chơi game hay nhất.",
                "hashtags": ["#game", "#tips", "#lienquan"],
            }
        ),
    ):
        body = {
            "pipeline_id": pid,
            "sample_caption": "Trận đấu kịch tính cùng đồng đội",
            "settings": {
                "tone": "exciting",
                "locked_hashtags": ["#shorts"],
            },
        }
        res = await run_ai_test(body)
        assert res["title"] == "Mẹo chơi game cực đỉnh"
        assert "#shorts" in res["hashtags"]
        assert "#game" in res["hashtags"]


@pytest.mark.asyncio
async def test_scan_error_marks_failed_not_completed():
    pid = "pipe_scan_fail"
    await pipelines_repo.create_pipeline(pid, "Scan Fail Pipe", "pipe-scan-fail")
    src = await sources_repo.create_source("src_fail_1", pid, "failing_user")

    mock_provider = AsyncMock()
    mock_provider.resolve_profile.return_value = TikTokProfile(
        user_id="failing_user",
        username="failing_user",
        display_name="Failing",
        follower_count=0,
        following_count=0,
        is_verified=False,
    )
    mock_provider.list_videos.side_effect = ProviderError("Upstream rate limit 429")

    with patch(
        "app.services.tiktok_scan.get_scan_provider",
        return_value=mock_provider,
    ):
        stats = await scan_source(src["id"], "scan_fail_run", scan_mode="manual")
        assert stats["discovered"] == 0

        updated_src = await sources_repo.get_source(src["id"])
        assert updated_src is not None
        assert updated_src["last_scan_status"] == "failed"
        assert "Upstream rate limit 429" in (updated_src["last_scan_error"] or "")


def test_call_toolnet_sync_handles_sse_trailer():
    from app.services.tiktok_ai_metadata import _call_toolnet_sync
    from unittest.mock import MagicMock

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = (
        '{"id":"chatcmpl-123","choices":[{"message":{"content":"{\\"title\\": \\"Test Video\\", \\"description\\": \\"Nice video\\", \\"hashtags\\": [\\"#test\\"]}"}}]}\n'
        'data: [DONE]\n\n'
    )

    with patch("httpx.post", return_value=mock_resp):
        res = _call_toolnet_sync("prompt", "system", "model")
        assert res["title"] == "Test Video"
        assert res["description"] == "Nice video"
        assert res["hashtags"] == ["#test"]


@pytest.mark.asyncio
async def test_pipeline_flow_with_scan_runs_returns_all_6_steps():
    from app.routes.flow import pipeline_flow
    from app.db.repositories import reels as reels_repo
    from app.db.repositories import scan_runs as scan_runs_repo

    pid = "pipe_flow_test"
    await pipelines_repo.create_pipeline(pid, "Flow Pipe", "pipe-flow")
    src = await sources_repo.create_source("src_flow_1", pid, "citrachoighelam_19")

    # Insert a scan run
    await scan_runs_repo.create_scan_run("scan_flow_1", src["id"], "manual")
    await scan_runs_repo.complete_scan_run(
        "scan_flow_1",
        discovered_count=15,
        inserted_count=15,
        existing_count=0,
        status="completed",
    )

    # Insert a reel
    await reels_repo.insert_reel_if_new(
        reel_db_id="reel_flow_1",
        source_id=src["id"],
        reel_id="7558026492685323528",
        reel_url="https://www.tiktok.com/@citra/video/7558026492685323528",
        caption="Test reel caption",
        thumbnail_url="https://p16.tiktokcdn.com/thumb.jpg",
    )

    flow = await pipeline_flow(pid)
    assert flow["pipeline_id"] == pid
    assert flow["steps"]["source"] in ("ready", "running", "error")
    assert flow["steps"]["inventory"] == "ready"
    assert "ai_metadata" in flow["steps"]
    assert "scheduler" in flow["steps"]
    assert "publisher" in flow["steps"]
    assert "youtube_destination" in flow["steps"]
    assert len(flow["steps"]) == 6

    # Verify last_scan is properly mapped dict and not raw tuple
    assert len(flow["sources"]) == 1
    src_data = flow["sources"][0]
    assert src_data["last_scan"] is not None
    assert src_data["last_scan"]["id"] == "scan_flow_1"
    assert src_data["last_scan"]["status"] == "completed"
    assert src_data["last_scan"]["discovered_count"] == 15


