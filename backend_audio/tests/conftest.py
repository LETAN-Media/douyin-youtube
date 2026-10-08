"""Shared fixtures: isolated SQLite DB per test."""

import pytest


@pytest.fixture()
def db(tmp_path, monkeypatch):
    from app.config import settings
    from app.db import client as dbc
    from app.db.migrations import migrate

    db_file = tmp_path / "audio_test.sqlite3"
    monkeypatch.setenv("AUDIO_ADMIN_TOKEN", "test_admin_token")
    monkeypatch.setenv("AUDIO_TURSO_URL", "")
    settings.AUDIO_ADMIN_TOKEN = "test_admin_token"
    settings.AUDIO_TURSO_URL = ""
    settings.AUDIO_DB_PATH = str(db_file)
    dbc.reset_client()
    migrate()
    yield db_file
    dbc.reset_client()
