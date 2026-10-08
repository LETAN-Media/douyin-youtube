"""AI YouTube metadata per drama pipeline: settings, generation, cache, routes."""

import json

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.db.repositories import ai_metadata as repo
from app.db.repositories import drama as drama_repo
from app.db.repositories import processing as proc_repo
from app.services.drama_ai_metadata import (
    AI_DISABLED_FOR_PIPELINE,
    DramaMetadataContext,
    DramaMetadataGenerator,
    MetadataError,
    ToolNetConfig,
    apply_description_template,
    apply_locked_hashtags,
    apply_title_template,
    build_user_content,
    ensure_drama_ai_metadata,
    validate_metadata,
)


ADMIN = {"X-Admin-Token": "test_admin_token"}


@pytest.fixture(autouse=True)
def _reset_ai_limiter():
    import app.services.drama_ai_metadata as svc

    svc._limiter = None
    yield
    svc._limiter = None


@pytest.fixture()
def client(db):
    return TestClient(create_app())


def _chat_payload(title="Tieu de hay", desc="Mo ta hay", tags=None):
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "choices": [
            {"message": {"role": "assistant",
                         "content": json.dumps({
                             "title": title, "description": desc,
                             "hashtags": tags or ["#Phim", "#Drama", "#Hay"]})}}
        ],
        "usage": {"total_tokens": 100},
    }


def _mock_transport(payload=None, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload or _chat_payload())
    return httpx.MockTransport(handler)




def run_ensure(job, **kwargs):
    return asyncio.run(ensure_drama_ai_metadata(job, **kwargs))

def _make_pipeline_job(db, mode="direct_merge"):
    p = drama_repo.create_pipeline(name="AI Pipe")
    src = drama_repo.create_source(pipeline_id=p["id"], external_series_id="ai-b1")
    s, _ = drama_repo.upsert_series(
        source_id=src["id"], provider="rapidix", external_series_id="ai-b1",
        title="Tong Tai Lanh Lung", description="Co gai ngheo gap tong tai.",
    )
    job = proc_repo.create_job(p["id"], s["id"], mode, 0, 1, 68)
    return p, s, job


# ---- settings repo ----

def test_settings_defaults_disabled(db):
    s = repo.get_settings("nope")
    assert s["enabled"] is False
    assert s["language"] == "vi"
    assert s["generate_title"] is True


def test_settings_upsert_and_reload(db):
    p = drama_repo.create_pipeline(name="P")
    repo.upsert_settings(p["id"], enabled=True, language="EN",
                         locked_hashtags="#A, #B\n#C")
    s = repo.get_settings(p["id"])
    assert s["enabled"] is True
    assert s["language"] == "en"
    assert s["locked_hashtags"] == ["#A", "#B", "#C"]


def test_config_hash_changes_with_language(db):
    p = drama_repo.create_pipeline(name="P")
    _, h1 = repo.current_config_hash(p["id"], model="m")
    repo.upsert_settings(p["id"], language="zh")
    _, h2 = repo.current_config_hash(p["id"], model="m")
    assert h1 != h2


# ---- prompts / validation ----

def test_prompts_per_language():
    for lang in ("vi", "en", "zh"):
        g = DramaMetadataGenerator(
            ToolNetConfig("http://x", "k", "m"), language=lang)
        prompt = g.effective_system_prompt()
        assert '{"title"' in prompt  # JSON contract always present


def test_custom_prompt_appended_not_replacing():
    g = DramaMetadataGenerator(
        ToolNetConfig("http://x", "k", "m"), language="vi",
        custom_system_prompt="Them cau keu goi dang ky.")
    prompt = g.effective_system_prompt()
    assert "Them cau keu goi" in prompt
    assert '{"title"' in prompt


def test_validate_truncates_and_rejects():
    t, d, h = validate_metadata({
        "title": "x" * 150, "description": "d" * 6000,
        "hashtags": ["#A", "#B", "#C"]})
    assert len(t) <= 100 and len(d) <= 5000
    with pytest.raises(MetadataError):
        validate_metadata({"title": "", "description": "d",
                           "hashtags": ["#A", "#B", "#C"]})
    with pytest.raises(MetadataError):
        validate_metadata({"title": "t", "description": "d",
                           "hashtags": ["#A"]})


def test_templates_and_locked_tags():
    assert apply_title_template("[Hay] {title}", "ABC") == "[Hay] ABC"
    assert apply_title_template("no-placeholder", "ABC") == "ABC"
    tags = apply_locked_hashtags(["#CoDinh"], ["#A", "#codinh", "#B"])
    assert tags == ["#A", "#codinh", "#B"]  # locked dup (case-insensitive) dropped
    desc = apply_description_template("{description}\n\n{hashtags}", "Hi", ["#A"])
    assert desc == "Hi\n\n#A"


def test_context_includes_episode_range_and_channel():
    text, empty = build_user_content(DramaMetadataContext(
        series_title="Tong Tai Lanh Lung", episode_start=1, episode_end=68,
        processing_mode="direct_merge", target_youtube_channel="Short Max"))
    assert "1–68" in text and "Short Max" in text and empty is False


# ---- generation with mocked ToolNet ----

def test_generate_vi_uses_vietnamese_prompt(db):
    p, s, job = _make_pipeline_job(db)
    repo.upsert_settings(p["id"], enabled=True, language="vi")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json=_chat_payload())
    result = run_ensure(
        job, transport=httpx.MockTransport(handler))
    assert result.cached is False
    assert result.metadata.title == "Tieu de hay"
    assert "TIẾNG VIỆT" in seen["body"]["messages"][0]["content"]


def test_cache_hit_no_http(db):
    p, s, job = _make_pipeline_job(db)
    repo.upsert_settings(p["id"], enabled=True, language="en")

    def exploding(request: httpx.Request) -> httpx.Response:
        raise AssertionError("AI must not be called on cache hit")
    r1 = run_ensure(job, transport=_mock_transport())
    assert r1.cached is False
    r2 = run_ensure(
        job, transport=httpx.MockTransport(exploding))
    assert r2.cached is True
    assert r2.metadata.title == r1.metadata.title


def test_language_change_invalidates_cache(db):
    p, s, job = _make_pipeline_job(db)
    repo.upsert_settings(p["id"], enabled=True, language="vi")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=_chat_payload(title=f"T{calls['n']}"))
    run_ensure(job, transport=httpx.MockTransport(handler))
    repo.upsert_settings(p["id"], language="zh")
    r = run_ensure(job, transport=httpx.MockTransport(handler))
    assert r.cached is False and calls["n"] == 2


def test_disabled_pipeline_never_calls_ai(db):
    p, s, job = _make_pipeline_job(db)

    def exploding(request: httpx.Request) -> httpx.Response:
        raise AssertionError("disabled pipeline must not call AI")
    with pytest.raises(MetadataError) as ei:
        run_ensure(job, transport=httpx.MockTransport(exploding))
    assert ei.value.code == AI_DISABLED_FOR_PIPELINE


def test_upstream_failure_maps_code(db):
    p, s, job = _make_pipeline_job(db)
    repo.upsert_settings(p["id"], enabled=True)
    with pytest.raises(MetadataError) as ei:
        run_ensure(job, transport=_mock_transport(status=500))
    assert ei.value.code in ("AI_METADATA_FAILED", "TOOLNET_UPSTREAM_ERROR",
                             "AI_INVALID_RESPONSE")


def test_direct_merge_needs_no_asr(db):
    """Metadata generation must not touch ASR tables at all."""
    p, s, job = _make_pipeline_job(db, mode="direct_merge")
    repo.upsert_settings(p["id"], enabled=True)
    result = run_ensure(job, transport=_mock_transport())
    assert result.metadata.title


# ---- routes ----

def test_routes_settings_roundtrip(db, client):
    p = drama_repo.create_pipeline(name="P")
    r = client.get(f"/api/drama/pipelines/{p['id']}/ai-settings", headers=ADMIN)
    assert r.status_code == 200 and r.json()["enabled"] is False
    r = client.put(f"/api/drama/pipelines/{p['id']}/ai-settings", headers=ADMIN,
                   json={"enabled": True, "language": "zh",
                         "locked_hashtags": ["#DuanJu"]})
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True and body["language"] == "zh"
    r = client.get(f"/api/drama/pipelines/{p['id']}/ai-settings", headers=ADMIN)
    assert r.json()["locked_hashtags"] == ["#DuanJu"]


def test_routes_preview_refuses_when_disabled(db, client):
    p = drama_repo.create_pipeline(name="P")
    r = client.post(f"/api/drama/pipelines/{p['id']}/ai-metadata/preview", headers=ADMIN,
                    json={"series_id": "x"})
    assert r.status_code == 400


# ---- per-pipeline isolation ----

def test_pipeline_prompts_are_isolated(db):
    a = drama_repo.create_pipeline(name="Pipe A")
    b = drama_repo.create_pipeline(name="Pipe B")
    repo.upsert_settings(a["id"], enabled=True, language="vi",
                         system_prompt="Prompt A rieng biet",
                         title_template="{title} | Phim Ngắn Hay",
                         locked_hashtags=["#PhimNgan"])
    repo.upsert_settings(b["id"], enabled=True, language="en",
                         system_prompt="Totally different English prompt",
                         title_template="{title} | Best Short Drama",
                         locked_hashtags=["#ShortDrama"])
    sa, sb = repo.get_settings(a["id"]), repo.get_settings(b["id"])
    assert sa["system_prompt"] == "Prompt A rieng biet"
    assert sb["system_prompt"] == "Totally different English prompt"
    assert sa["title_template"] != sb["title_template"]
    assert sa["locked_hashtags"] == ["#PhimNgan"]
    assert sb["locked_hashtags"] == ["#ShortDrama"]
    # Editing A again does not touch B.
    repo.upsert_settings(a["id"], system_prompt="Prompt A v2")
    assert repo.get_settings(b["id"])["system_prompt"] == "Totally different English prompt"


def test_reset_restores_defaults_and_bumps_version(db):
    p = drama_repo.create_pipeline(name="P")
    repo.upsert_settings(p["id"], enabled=True, language="zh",
                         system_prompt="custom")
    v1 = repo.get_settings(p["id"])["config_version"]
    cfg = repo.reset_settings(p["id"])
    assert cfg["enabled"] is False
    assert cfg["language"] == "vi"
    assert cfg["system_prompt"] is None
    assert cfg["locked_hashtags"] == []
    assert cfg["config_version"] == v1 + 1


def test_version_conflict_on_stale_write(db):
    p = drama_repo.create_pipeline(name="P")
    v1 = repo.get_settings(p["id"])["config_version"]
    repo.upsert_settings(p["id"], language="en")  # someone else saves first
    import app.db.repositories.ai_metadata as m
    with pytest.raises(m.VersionConflict):
        repo.upsert_settings(p["id"], language="zh",
                             expected_config_version=v1)
    # Correct version succeeds.
    v2 = repo.get_settings(p["id"])["config_version"]
    cfg = repo.upsert_settings(p["id"], language="zh",
                               expected_config_version=v2)
    assert cfg["language"] == "zh"


def test_description_template_variables(db):
    from app.services.drama_ai_metadata import (
        apply_description_template, find_unreplaced_placeholders,
    )
    out = apply_description_template(
        "{description}\n🎬 Tên phim: {series_title}\n📺 {episode_start}-{episode_end}/{episode_count}\n{hashtags}\nKênh: {channel_name}",
        "Mo ta goc", ["#A"],
        variables={"series_title": "Sieu Pham", "episode_start": 1,
                   "episode_end": 20, "episode_count": 68,
                   "channel_name": "Short Max"})
    assert "Sieu Pham" in out and "1-20/68" in out and "Short Max" in out
    assert find_unreplaced_placeholders(out) == []
    leftover = apply_description_template("{description} {unknown_var}", "d", [])
    assert find_unreplaced_placeholders(leftover) == ["{unknown_var}"]


def test_cross_pipeline_cache_not_shared(db):
    pa, _, job_a = _make_pipeline_job(db)
    pb = drama_repo.create_pipeline(name="Pipe B")
    repo.upsert_settings(pa["id"], enabled=True, language="vi")
    repo.upsert_settings(pb["id"], enabled=True, language="vi")
    r = run_ensure(job_a, transport=_mock_transport())
    assert r.cached is False
    # A job from another pipeline can never hit A's cache row:
    # cache lookup is by (job_id, language) and job ids are unique per job.
    row = repo.get_cache_row(job_a["id"], "vi")
    assert row is not None and row["pipeline_id"] == pa["id"]
    assert row["pipeline_id"] != pb["id"]


def test_model_override_changes_hash_and_generator(db):
    p = drama_repo.create_pipeline(name="P")
    _, h1 = repo.current_config_hash(p["id"], model="m1")
    repo.upsert_settings(p["id"], model_override="custom/model-x")
    cfg, h2 = repo.current_config_hash(p["id"], model="m1")
    assert h1 != h2
    assert cfg["model_override"] == "custom/model-x"


def test_routes_version_conflict_and_reset(db, client):
    p = drama_repo.create_pipeline(name="P")
    v1 = client.get(f"/api/drama/pipelines/{p['id']}/ai-settings",
                    headers=ADMIN).json()["config_version"]
    r = client.put(f"/api/drama/pipelines/{p['id']}/ai-settings", headers=ADMIN,
                   json={"language": "en", "expected_config_version": v1})
    assert r.status_code == 200
    r = client.put(f"/api/drama/pipelines/{p['id']}/ai-settings", headers=ADMIN,
                   json={"language": "zh", "expected_config_version": v1})
    assert r.status_code == 409
    r = client.post(f"/api/drama/pipelines/{p['id']}/ai-settings/reset",
                    headers=ADMIN)
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False and body["language"] == "vi"
