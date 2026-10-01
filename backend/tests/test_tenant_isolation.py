"""Backend-enforced tenant isolation tests (Phase 16-17).

Runs against an ISOLATED sqlite database (never production): the app
lifespan is replaced with a no-op and the ``get_db`` dependency is
overridden. Covers the spec matrix:

- User A sees only Channel A1, User B only B1, admin sees all.
- Direct-ID access across tenants returns 404 (channels, destinations,
  inventory, publications, jobs, comments, analytics, research, DNA,
  publish, OAuth, update/delete).
"""

import json
import os

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/tenant_iso_test.db")
os.environ.setdefault("ADMIN_TOKEN", "test-admin-token-xyz")

from contextlib import asynccontextmanager  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import auth as auth_lib  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Destination,
    DouyinSource,
    DouyinVideo,
    Pipeline,
    Publication,
    User,
    UserSession,
    Workspace,
    WorkspaceMember,
    YouTubeComment,
)


@asynccontextmanager
async def _noop_lifespan(application):
    yield


app.router.lifespan_context = _noop_lifespan

TEST_DB_URL = "sqlite:////tmp/tenant_iso_test.db"
try:
    os.remove("/tmp/tenant_iso_test.db")
except FileNotFoundError:
    pass

test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(bind=test_engine)
TestingSession = sessionmaker(bind=test_engine, expire_on_commit=False)


def _override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db

ADMIN_HEADERS = {"X-Admin-Token": settings.admin_token}


def _seed():
    with TestingSession() as db:
        ws_admin = Workspace(name="Admin Workspace")
        ws_a = Workspace(name="Workspace A")
        ws_b = Workspace(name="Workspace B")
        db.add_all([ws_admin, ws_a, ws_b])
        db.flush()

        admin = User(
            email="admin@test.local",
            password_hash=auth_lib.hash_password("admin-pass-123"),
            display_name="Sys Admin",
            status="active",
            is_system_admin=True,
        )
        user_a = User(
            email="a@test.local",
            password_hash=auth_lib.hash_password("usera-pass-123"),
            display_name="User A",
            status="active",
        )
        user_b = User(
            email="b@test.local",
            password_hash=auth_lib.hash_password("userb-pass-123"),
            display_name="User B",
            status="active",
        )
        db.add_all([admin, user_a, user_b])
        db.flush()
        db.add_all(
            [
                WorkspaceMember(
                    workspace_id=ws_admin.id, user_id=admin.id, role="owner"
                ),
                WorkspaceMember(
                    workspace_id=ws_a.id, user_id=user_a.id, role="owner"
                ),
                WorkspaceMember(
                    workspace_id=ws_b.id, user_id=user_b.id, role="owner"
                ),
            ]
        )

        pipe_admin = Pipeline(
            name="Admin Pipe",
            slug="admin-pipe",
            workspace_id=ws_admin.id,
            enabled=True,
        )
        pipe_a = Pipeline(
            name="Pipe A", slug="pipe-a", workspace_id=ws_a.id, enabled=True
        )
        pipe_b = Pipeline(
            name="Pipe B", slug="pipe-b", workspace_id=ws_b.id, enabled=True
        )
        db.add_all([pipe_admin, pipe_a, pipe_b])
        db.flush()

        dest_admin = Destination(
            pipeline_id=pipe_admin.id,
            workspace_id=ws_admin.id,
            platform="youtube",
            name="ADMIN-A",
            enabled=True,
        )
        dest_a1 = Destination(
            pipeline_id=pipe_a.id,
            workspace_id=ws_a.id,
            platform="youtube",
            name="A1",
            enabled=True,
        )
        dest_b1 = Destination(
            pipeline_id=pipe_b.id,
            workspace_id=ws_b.id,
            platform="youtube",
            name="B1",
            enabled=True,
        )
        db.add_all([dest_admin, dest_a1, dest_b1])
        db.flush()

        src_a = DouyinSource(
            pipeline_id=pipe_a.id,
            workspace_id=ws_a.id,
            name="Source A",
            profile_url="https://www.douyin.com/user/aaa",
            enabled=True,
        )
        src_b = DouyinSource(
            pipeline_id=pipe_b.id,
            workspace_id=ws_b.id,
            name="Source B",
            profile_url="https://www.douyin.com/user/bbb",
            enabled=True,
        )
        db.add_all([src_a, src_b])
        db.flush()

        vid_a = DouyinVideo(
            source_id=src_a.id,
            pipeline_id=pipe_a.id,
            workspace_id=ws_a.id,
            video_id="aweme-a-1",
            title="Video A1",
            description="desc",
            url="https://v.douyin.com/aaa/",
            status="new",
        )
        db.add(vid_a)
        db.flush()

        pub_a = Publication(
            pipeline_id=pipe_a.id,
            workspace_id=ws_a.id,
            douyin_video_id=vid_a.id,
            destination_id=dest_a1.id,
            platform="youtube",
            status="queued",
        )
        db.add(pub_a)
        db.flush()

        vid_b = DouyinVideo(
            source_id=src_b.id,
            pipeline_id=pipe_b.id,
            workspace_id=ws_b.id,
            video_id="aweme-b-1",
            title="Video B1",
            description="desc b",
            url="https://v.douyin.com/bbb/",
            status="new",
        )
        db.add(vid_b)
        db.flush()
        pub_b = Publication(
            pipeline_id=pipe_b.id,
            workspace_id=ws_b.id,
            douyin_video_id=vid_b.id,
            destination_id=dest_b1.id,
            platform="youtube",
            status="queued",
        )
        db.add(pub_b)
        db.flush()

        from app.models import VideoJob as _VJ

        job_b = _VJ(
            source_url="https://v.douyin.com/bbb/",
            title="Job B",
            status="pending",
            pipeline_id=pipe_b.id,
            workspace_id=ws_b.id,
            destination_id=dest_b1.id,
            publication_id=pub_b.id,
        )
        db.add(job_b)

        comment_b = YouTubeComment(
            destination_id=dest_b1.id,
            workspace_id=ws_b.id,
            video_id="yt-b-1",
            youtube_comment_id="comment-b-1",
            text_original="hello B",
            comment_text="hello B",
            status="new",
            reply_status="new",
        )
        db.add(comment_b)
        db.commit()
        return {
            "dest_admin": dest_admin.id,
            "dest_a1": dest_a1.id,
            "dest_b1": dest_b1.id,
            "pipe_a": pipe_a.id,
            "pipe_b": pipe_b.id,
            "src_a": src_a.id,
            "src_b": src_b.id,
            "pub_a": pub_a.id,
            "pub_b": pub_b.id,
            "job_b": job_b.id,
            "vid_b": vid_b.video_id,
        }


IDS = _seed()
client = TestClient(app, raise_server_exceptions=False)


def _login(email, password):
    res = client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert res.status_code == 200, res.text
    return {"X-Session-Token": res.json()["token"]}


HA = _login("a@test.local", "usera-pass-123")
HB = _login("b@test.local", "userb-pass-123")


def test_login_rejects_bad_credentials():
    bad = client.post(
        "/api/auth/login",
        json={"email": "a@test.local", "password": "wrong-pass"},
    )
    assert bad.status_code == 401
    unknown = client.post(
        "/api/auth/login", json={"email": "no@test.local", "password": "x" * 12}
    )
    assert unknown.status_code == 401


def test_me_returns_workspace():
    res = client.get("/api/auth/me", headers=HA)
    assert res.status_code == 200
    body = res.json()
    assert body["user"]["email"] == "a@test.local"
    assert [w["name"] for w in body["workspaces"]] == ["Workspace A"]


def test_user_a_sees_only_a1():
    res = client.get("/api/channels", headers=HA)
    assert res.status_code == 200
    names = [c["channel_title"] for c in res.json()]
    assert names == ["A1"], names


def test_user_b_sees_only_b1():
    res = client.get("/api/channels", headers=HB)
    assert res.status_code == 200
    names = [c["channel_title"] for c in res.json()]
    assert names == ["B1"], names


def test_admin_sees_all_channels():
    res = client.get("/api/channels", headers=ADMIN_HEADERS)
    assert res.status_code == 200
    names = sorted(c["channel_title"] for c in res.json())
    assert names == ["A1", "ADMIN-A", "B1"], names


def test_direct_channel_id_attack():
    # A -> B1 detail
    assert (
        client.get(f"/api/channels/{IDS['dest_b1']}", headers=HA).status_code
        == 404
    )
    # A -> ADMIN detail
    assert (
        client.get(f"/api/channels/{IDS['dest_admin']}", headers=HA).status_code
        == 404
    )
    # B -> A1 detail
    assert (
        client.get(f"/api/channels/{IDS['dest_a1']}", headers=HB).status_code
        == 404
    )


def test_destination_update_delete_attack():
    assert (
        client.patch(
            f"/api/destinations/{IDS['dest_b1']}",
            headers=HA,
            json={"name": "HACKED"},
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/destinations/{IDS['dest_b1']}", headers=HA
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/destinations/{IDS['dest_b1']}", headers=HA
        ).status_code
        == 404
    )


def test_inventory_isolation():
    ok = client.get(f"/api/channels/{IDS['dest_a1']}/inventory", headers=HA)
    assert ok.status_code == 200
    assert any(
        i["video_id"] == "aweme-a-1" for i in ok.json()["items"]
    )
    # A must not read B's inventory
    assert (
        client.get(
            f"/api/channels/{IDS['dest_b1']}/inventory", headers=HA
        ).status_code
        == 404
    )
    # A must not read B's pipeline inventory
    assert (
        client.get(
            f"/api/pipelines/{IDS['pipe_b']}/inventory", headers=HA
        ).status_code
        == 404
    )


def test_publication_job_isolation():
    # B's user cannot see A's publication
    assert (
        client.get(
            f"/api/publications/{IDS['pub_a']}", headers=HB
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/publications/{IDS['pub_a']}/retry", headers=HB
        ).status_code
        == 404
    )
    # B cannot see A's publications or jobs (cross-tenant = 404 on direct id).
    # B's own lists must contain ONLY B's rows, never A's.
    assert (
        client.get(
            f"/api/publications/{IDS['pub_a']}", headers=HB
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/publications/{IDS['pub_a']}/retry", headers=HB
        ).status_code
        == 404
    )
    # B's publication list must contain only B's own publication, not A's.
    res = client.get("/api/publications", headers=HB)
    assert res.status_code == 200
    pub_ids = [p["id"] for p in res.json()]
    assert IDS["pub_b"] in pub_ids, "B should see own publication"
    assert IDS["pub_a"] not in pub_ids, "B must not see A's publication"
    # B's jobs list must contain only B's own job, not A's.
    res = client.get("/api/jobs", headers=HB)
    assert res.status_code == 200
    job_ids = [j["id"] for j in res.json()]
    assert IDS["job_b"] in job_ids, "B should see own job"


def test_comments_isolation():
    # A lists own (empty) comments fine
    res = client.get(
        f"/api/channels/{IDS['dest_a1']}/comments", headers=HA
    )
    assert res.status_code == 200
    # A cannot list B's comments
    assert (
        client.get(
            f"/api/channels/{IDS['dest_b1']}/comments", headers=HA
        ).status_code
        == 404
    )
    # A cannot reply to B's comment even with direct id
    assert (
        client.post(
            f"/api/channels/{IDS['dest_b1']}/comments/comment-b-1/reply",
            headers=HA,
            json={"text": "hack"},
        ).status_code
        == 404
    )


def test_analytics_research_dna_isolation():
    for path in ("analytics", "research", "dna"):
        res = client.get(
            f"/api/channels/{IDS['dest_b1']}/{path}", headers=HA
        )
        assert res.status_code == 404, path
    # own channel endpoints are reachable (may be empty, never 404)
    for path in ("research", "dna"):
        res = client.get(f"/api/channels/{IDS['dest_a1']}/{path}", headers=HA)
        assert res.status_code == 200, path


def test_publish_into_foreign_channel_rejected():
    res = client.post(
        "/api/manual/publish",
        headers=HA,
        json={
            "source_url": "https://v.douyin.com/evil/",
            "source_title": "evil",
            "destination_ids": [IDS["dest_b1"]],
        },
    )
    assert res.status_code == 404


def test_oauth_into_foreign_channel_rejected():
    res = client.post(
        f"/api/youtube/oauth-url?destination_id={IDS['dest_b1']}",
        headers=HA,
    )
    assert res.status_code == 404


def test_channel_update_delete_attack():
    assert (
        client.patch(
            f"/api/channels/{IDS['dest_b1']}",
            headers=HA,
            json={"daily_upload_limit": 9},
        ).status_code
        == 404
    )


def test_source_attack():
    # B cannot touch A's source
    assert (
        client.get(f"/api/sources/{IDS['src_a']}", headers=HB).status_code
        == 404
    )
    assert (
        client.delete(f"/api/sources/{IDS['src_a']}", headers=HB).status_code
        == 404
    )


def test_admin_user_management_and_regular_forbidden():
    # Regular user cannot manage users
    assert client.get("/api/admin/users", headers=HA).status_code == 404
    # Admin creates a user with an empty workspace
    res = client.post(
        "/api/admin/users",
        headers=ADMIN_HEADERS,
        json={
            "email": "c@test.local",
            "password": "userc-pass-123",
            "display_name": "User C",
            "workspace_name": "Workspace C",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["workspace"]["name"] == "Workspace C"
    user_id = body["user"]["id"]
    # New user logs in and sees an empty channel list
    hc = _login("c@test.local", "userc-pass-123")
    res = client.get("/api/channels", headers=hc)
    assert res.status_code == 200
    assert res.json() == []
    # Admin disables the user -> login fails
    res = client.patch(
        f"/api/admin/users/{user_id}",
        headers=ADMIN_HEADERS,
        json={"status": "disabled"},
    )
    assert res.status_code == 200
    bad = client.post(
        "/api/auth/login",
        json={"email": "c@test.local", "password": "userc-pass-123"},
    )
    assert bad.status_code == 401


def test_change_password():
    global HA
    res = client.post(
        "/api/auth/change-password",
        headers=HA,
        json={
            "current_password": "usera-pass-123",
            "new_password": "usera-new-pass-456",
        },
    )
    assert res.status_code == 200, res.text
    # new password works
    _login("a@test.local", "usera-new-pass-456")
    # revert for other tests that re-login
    with TestingSession() as db:
        user = db.query(User).filter(User.email == "a@test.local").first()
        user.password_hash = auth_lib.hash_password("usera-pass-123")
        db.query(UserSession).filter(
            UserSession.user_id == user.id
        ).delete()
        db.commit()
    HA = _login("a@test.local", "usera-pass-123")


def test_logout_revokes_session():
    headers = _login("b@test.local", "userb-pass-123")
    res = client.post("/api/auth/logout", headers=headers)
    assert res.status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 401


# ---------------- §30 extended matrix ----------------

def test_channel_patch_and_pipeline_delete_attack():
    # A cannot PATCH B's channel
    assert (
        client.patch(
            f"/api/channels/{IDS['dest_b1']}",
            headers=HA,
            json={"daily_upload_limit": 9},
        ).status_code
        == 404
    )
    # A cannot DELETE B's pipeline
    assert (
        client.delete(
            f"/api/pipelines/{IDS['pipe_b']}", headers=HA
        ).status_code
        == 404
    )
    # A cannot read B's pipeline
    assert (
        client.get(f"/api/pipelines/{IDS['pipe_b']}", headers=HA).status_code
        == 404
    )
    # A cannot list B's pipeline sources
    assert (
        client.get(
            f"/api/pipelines/{IDS['pipe_b']}/sources", headers=HA
        ).status_code
        == 404
    )


def test_job_direct_attack():
    # A cannot read/retry B's job
    assert (
        client.get(f"/api/jobs/{IDS['job_b']}", headers=HA).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/jobs/{IDS['job_b']}/retry", headers=HA
        ).status_code
        == 404
    )
    # A sees only own jobs (none) while B sees B's job
    assert client.get("/api/jobs", headers=HA).json() == []
    jobs_b = client.get("/api/jobs", headers=HB).json()
    assert [j["id"] for j in jobs_b] == [IDS["job_b"]]


def test_source_inventory_and_sync_attack():
    # A cannot read B's source inventory
    assert (
        client.get(
            f"/api/sources/{IDS['src_b']}/inventory", headers=HA
        ).status_code
        == 404
    )
    # A cannot trigger sync/import/refresh on B's source
    for path in ("sync", "initial-import", "refresh"):
        res = client.post(
            f"/api/sources/{IDS['src_b']}/{path}", headers=HA
        )
        assert res.status_code == 404, path
    # A cannot pause/resume/scan B's source
    for path in ("pause", "resume", "scan"):
        res = client.post(f"/api/sources/{IDS['src_b']}/{path}", headers=HA)
        assert res.status_code == 404, path


def test_publication_actions_attack():
    # Skip/reschedule/schedule endpoints on B's publication
    assert (
        client.post(
            f"/api/publications/{IDS['pub_b']}/skip", headers=HA
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/publications/{IDS['pub_b']}/reschedule",
            headers=HA,
            json={"scheduled_at": "2030-01-01T10:00:00+00:00"},
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/manual/publications/{IDS['pub_b']}", headers=HA
        ).status_code
        == 404
    )


def test_comment_settings_and_overrides_attack():
    assert (
        client.get(
            f"/api/channels/{IDS['dest_b1']}/comment-reply-settings",
            headers=HA,
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/channels/{IDS['dest_b1']}/overrides", headers=HA
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/channels/{IDS['dest_b1']}/schedule-capacity",
            headers=HA,
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/channels/{IDS['dest_b1']}/upcoming", headers=HA
        ).status_code
        == 404
    )


def test_rate_limit_blocks_brute_force():
    # 10+ failures from a fresh identity trigger 429 (in-memory guard).
    for _ in range(11):
        res = client.post(
            "/api/auth/login",
            json={"email": "ghost@t.local", "password": "wrong-wrong-1"},
        )
    assert res.status_code == 429, res.status_code


# ---------------- §31 channel AI isolation ----------------

class _FakeResp:
    def __init__(self, payload: dict):
        import json as _json

        self.text = _json.dumps(payload)

    def raise_for_status(self):
        return None


def _canned_ai(title: str, tag: str):
    inner = {
        "match_level": "match",
        "reason": "ok",
        "title": title,
        "description": f"desc {tag}",
        "hashtags": [f"#{tag}", "#dynamic1", "#dynamic2", "#dynamic3", "#dynamic4"],
        "final_description": f"desc {tag}\n\n#{tag}",
        "content_match": True,
    }
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(inner),
                }
            }
        ]
    }


def test_channel_ai_prompt_and_locked_tags_isolation(monkeypatch):
    """Three niches (pet / dance / handsome) must never leak into each
    other's AI payload; locked hashtags/tags stay per-channel."""
    import app.ai_metadata as am
    from app.models import Destination as _Dest
    from app.models import YouTubeChannelDNA as _DNA

    captured: dict[str, str] = {}

    def _fake_post(url, headers=None, json=None, timeout=None):
        system = ""
        try:
            for m in (json or {}).get("messages", []):
                if m.get("role") == "system":
                    system += str(m.get("content") or "")
        except Exception:
            system = ""
        # Tag the capture by destination marker embedded in the prompt.
        for marker in ("FLUFFY-MARKER", "JOYBEAT-MARKER", "HBU-MARKER"):
            if marker in system:
                captured[marker] = system
        # Figure out which channel from the marker in the prompt.
        title = "Generated Title"
        tag = "dynamicx"
        if "FLUFFY-MARKER" in system:
            title, tag = "Fluffy Title", "fluffy"
        elif "JOYBEAT-MARKER" in system:
            title, tag = "JoyBeat Title", "joybeat"
        elif "HBU-MARKER" in system:
            title, tag = "HBU Title", "handsome"
        return _FakeResp(_canned_ai(title, tag))

    monkeypatch.setattr(am, "httpx", type("X", (), {"post": staticmethod(_fake_post)}))

    # Patch the DNA session to the isolated sqlite DB.
    import app.db as _db

    monkeypatch.setattr(_db, "SessionLocal", TestingSession)
    monkeypatch.setattr(am, "settings", type(
        "S",
        (),
        {
            "ai_enabled": True,
            "ai_api_key": "test",
            "ai_base_url": "http://x",
            "ai_model": "m",
        },
    )())

    with TestingSession() as db:
        specs = [
            ("FLUFFY-MARKER", IDS["dest_a1"], ["#fluffy", "#cutepets"], "pet"),
            ("JOYBEAT-MARKER", IDS["dest_b1"], ["#joybeat", "#dance"], "dance"),
            ("HBU-MARKER", IDS["dest_admin"], ["#handsome", "#menstyle"], "style"),
        ]
        for marker, dest_id, locked, niche in specs:
            d = db.get(_Dest, dest_id)
            d.prompt_override = f"{marker} Write titles for {niche} only."
            d.metadata_profile = f"{niche} profile"
            if db.query(_DNA).filter(_DNA.destination_id == dest_id).first() is None:
                db.add(
                    _DNA(
                        destination_id=dest_id,
                        workspace_id=d.workspace_id,
                        primary_niche=niche,
                        locked_hashtags=locked,
                        locked_tags=[f"{niche}-tag1", f"{niche}-tag2"],
                    )
                )
        db.commit()

        results = {}
        for marker, dest_id, locked, niche in specs:
            d = db.get(_Dest, dest_id)
            out = am.generate_metadata_structured(
                context_text=f"a cute video about {niche}",
                pipeline=None,
                destination=d,
            )
            assert out is not None, f"AI generation failed for {marker}"
            results[marker] = out

    # Each channel's system prompt contains ONLY its own marker.
    assert set(captured.keys()) == {"FLUFFY-MARKER", "JOYBEAT-MARKER", "HBU-MARKER"}
    assert "JOYBEAT-MARKER" not in captured["FLUFFY-MARKER"]
    assert "FLUFFY-MARKER" not in captured["JOYBEAT-MARKER"]
    assert "HBU-MARKER" not in captured["FLUFFY-MARKER"]
    # Locked hashtags enforced per channel in final output.
    assert "#fluffy" in results["FLUFFY-MARKER"]["hashtags"]
    assert "#joybeat" in results["JOYBEAT-MARKER"]["hashtags"]
    assert "#handsome" in results["HBU-MARKER"]["hashtags"]
    assert "#joybeat" not in results["FLUFFY-MARKER"]["hashtags"]
