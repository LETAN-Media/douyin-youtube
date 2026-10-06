"""Shared fixtures: isolated SQLite DB per test."""

import pytest


@pytest.fixture()
def db(tmp_path, monkeypatch):
    from app.config import settings
    from app.db import client as dbc

    db_file = tmp_path / "drama_test.sqlite3"
    monkeypatch.setenv("DRAMA_ADMIN_TOKEN", "test_admin_token")
    monkeypatch.setenv("DRAMA_TURSO_URL", "")
    settings.DRAMA_ADMIN_TOKEN = "test_admin_token"
    settings.DRAMA_TURSO_URL = ""
    settings.DRAMA_DB_PATH = str(db_file)
    settings.RAPIDIX_KEY = "test_rapidix_key"
    settings.RAPIDAPI_HOST = "test-host.p.rapidapi.com"
    settings.RAPIDAPI_BASE_URL = "https://test-host.p.rapidapi.com"
    settings.RAPIDIX_SEARCH_PATH = "/search"
    settings.RAPIDIX_EPISODES_PATH = "/episodes"
    settings.RAPIDIX_EPISODE_PATH = "/episode"
    dbc.reset_client()
    dbc.migrate()
    yield db_file
    dbc.reset_client()
