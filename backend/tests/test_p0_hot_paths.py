"""Regression coverage for the dashboard P0 hot paths.

These tests use a private in-memory SQLite database (never production) and
assert the two properties that matter for the P0 fix:

1. Pipeline hot-path fetches do not eager-load the selectin object graph.
2. Session authentication does not COMMIT on every request; it only refreshes
   ``last_used_at`` after the configured interval, while still rejecting
   expired/disabled sessions.
"""

import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/p0_hot_paths_test.db")
os.environ.setdefault("ADMIN_TOKEN", "test-admin-token-p0")

import pytest  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import auth as auth_lib  # noqa: E402
from app.db import Base  # noqa: E402
from app.main import list_pipelines  # noqa: E402
from app.models import (  # noqa: E402
    Destination,
    DouyinSource,
    DouyinVideo,
    Pipeline,
    Publication,
    User,
    UserSession,
)
from app.tenancy import require_pipeline  # noqa: E402


@contextmanager
def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    try:
        yield engine, db
    finally:
        db.close()
        engine.dispose()


def _seed_graph(db: Session) -> Pipeline:
    pipeline = Pipeline(name="Hot Path", slug="hot-path", enabled=True)
    db.add(pipeline)
    db.flush()

    source = DouyinSource(
        pipeline_id=pipeline.id,
        platform="douyin",
        name="Source 1",
    )
    destination = Destination(
        pipeline_id=pipeline.id,
        platform="youtube",
        name="Destination 1",
    )
    db.add_all([source, destination])
    db.flush()

    video = DouyinVideo(
        pipeline_id=pipeline.id,
        source_id=source.id,
        video_id="video-1",
        url="https://example.test/video/1",
    )
    db.add(video)
    db.flush()
    db.add(
        Publication(
            pipeline_id=pipeline.id,
            douyin_video_id=video.id,
            destination_id=destination.id,
            platform="youtube",
            status="queued",
        )
    )
    db.commit()
    return pipeline


def _count_statements(engine, fn):
    statements = []

    def before(conn, cursor, statement, parameters, context, executemany):
        statements.append(" ".join(statement.split()))

    event.listen(engine, "before_cursor_execute", before)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", before)
    return statements


def test_hot_pipeline_load_skips_selectin_graph():
    with _session() as (engine, db):
        pipeline = _seed_graph(db)
        db.expunge_all()

        lean = _count_statements(engine, lambda: require_pipeline(db, pipeline.id))
        assert len(lean) == 1, lean
        db.expunge_all()

        eager = _count_statements(
            engine,
            lambda: require_pipeline(db, pipeline.id, include_relations=True),
        )
        assert len(eager) >= 10, eager


def test_list_pipelines_does_not_eager_load_children():
    with _session() as (engine, db):
        _seed_graph(db)
        db.expunge_all()
        statements = _count_statements(engine, lambda: list_pipelines(db))
        assert len(statements) == 1, statements


def _seed_user(db: Session, *, status: str = "active") -> tuple[User, str, str]:
    now = datetime.now(timezone.utc)
    user = User(
        email=f"{status}@example.test",
        password_hash="not-used",
        display_name="Test",
        status=status,
        last_login_at=now,
    )
    db.add(user)
    db.flush()
    token = auth_lib.new_session_token()
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=auth_lib.hash_session_token(token),
            expires_at=now + timedelta(hours=1),
            last_used_at=now - timedelta(seconds=1),
        )
    )
    db.commit()
    return user, token, auth_lib.hash_session_token(token)


def test_session_touch_is_throttled(monkeypatch):
    with _session() as (engine, db):
        _, token, _ = _seed_user(db)
        # Use direct interval argument simulation instead of mutating global settings
        # Save original and restore to avoid test pollution
        original_interval = getattr(auth_lib.settings, "session_touch_interval_seconds", 300)
        
        try:
            monkeypatch.setattr(auth_lib.settings, "session_touch_interval_seconds", 300)
            updates = _count_statements(
                engine,
                lambda: auth_lib.lookup_session(db, token),
            )
            assert not [s for s in updates if s.startswith("UPDATE")], updates

            monkeypatch.setattr(auth_lib.settings, "session_touch_interval_seconds", 0)
            updates = _count_statements(
                engine,
                lambda: auth_lib.lookup_session(db, token),
            )
            assert [s for s in updates if s.startswith("UPDATE")], updates
        finally:
            # Explicitly restore original value
            monkeypatch.setattr(auth_lib.settings, "session_touch_interval_seconds", original_interval)


def test_expired_and_disabled_sessions_never_touch():
    with _session() as (engine, db):
        _, expired_token, _ = _seed_user(db)
        expired = (
            db.query(UserSession)
            .filter(UserSession.token_hash == auth_lib.hash_session_token(expired_token))
            .one()
        )
        expired.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

        updates = _count_statements(
            engine,
            lambda: auth_lib.lookup_session(db, expired_token),
        )
        assert auth_lib.lookup_session(db, expired_token) is None
        assert not [s for s in updates if s.startswith("UPDATE")], updates

    with _session() as (engine, db):
        _seed_user(db, status="disabled")
        token = auth_lib.new_session_token()
        user = db.query(User).filter(User.email == "disabled@example.test").one()
        db.add(
            UserSession(
                user_id=user.id,
                token_hash=auth_lib.hash_session_token(token),
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                last_used_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            )
        )
        db.commit()
        updates = _count_statements(
            engine,
            lambda: auth_lib.lookup_session(db, token),
        )
        assert auth_lib.lookup_session(db, token) is None
        assert not [s for s in updates if s.startswith("UPDATE")], updates
