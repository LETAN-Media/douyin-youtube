"""Tests for Turso connection, normalization, timeouts, and auth."""

import pytest
import os
from unittest import mock
import libsql_client
from app.db import client as dbc
from app.config import settings

def test_empty_url_local_sqlite(monkeypatch, tmp_path):
    monkeypatch.setenv("DRAMA_TURSO_URL", "")
    settings.DRAMA_TURSO_URL = ""
    settings.DRAMA_DB_PATH = str(tmp_path / "test.sqlite3")
    dbc.reset_client()
    
    client = dbc.get_client()
    assert isinstance(client, dbc.LocalSQLiteDatabase)

def test_file_url_local_sqlite(monkeypatch, tmp_path):
    db_file = str(tmp_path / "test2.sqlite3")
    monkeypatch.setenv("DRAMA_TURSO_URL", f"file:{db_file}")
    settings.DRAMA_TURSO_URL = f"file:{db_file}"
    dbc.reset_client()
    
    client = dbc.get_client()
    assert isinstance(client, dbc.LocalSQLiteDatabase)

@mock.patch("app.db.client.libsql_client.create_client_sync")
def test_libsql_url_normalization(mock_create, monkeypatch):
    monkeypatch.setenv("DRAMA_TURSO_URL", "libsql://test.turso.io")
    settings.DRAMA_TURSO_URL = "libsql://test.turso.io"
    settings.DRAMA_TURSO_TOKEN = "tok"
    dbc.reset_client()
    
    mock_create.return_value = mock.Mock()
    client = dbc.get_client()
    assert isinstance(client, dbc.RemoteTursoDatabase)
    assert client.url == "https://test.turso.io"
    assert client.token == "tok"

@mock.patch("app.db.client.libsql_client.create_client_sync")
def test_https_turso_url(mock_create, monkeypatch):
    monkeypatch.setenv("DRAMA_TURSO_URL", "https://test.turso.io")
    settings.DRAMA_TURSO_URL = "https://test.turso.io"
    settings.DRAMA_TURSO_TOKEN = "tok2"
    dbc.reset_client()
    
    mock_create.return_value = mock.Mock()
    client = dbc.get_client()
    assert isinstance(client, dbc.RemoteTursoDatabase)
    assert client.url == "https://test.turso.io"
    assert client.token == "tok2"

@mock.patch("app.db.client.libsql_client.create_client_sync")
def test_missing_turso_token(mock_create, monkeypatch):
    monkeypatch.setenv("DRAMA_TURSO_URL", "https://test.turso.io")
    settings.DRAMA_TURSO_URL = "https://test.turso.io"
    settings.DRAMA_TURSO_TOKEN = ""
    dbc.reset_client()
    
    mock_create.return_value = mock.Mock()
    client = dbc.get_client()
    assert client.token == ""

@mock.patch("app.db.client.get_client")
def test_timeout_handling(mock_get_client, monkeypatch):
    monkeypatch.setenv("DRAMA_TURSO_URL", "https://test.turso.io")
    settings.DRAMA_TURSO_URL = "https://test.turso.io"
    dbc.reset_client()
    
    # Mock execute to simulate a timeout or network hang
    import time
    def _hang(*args):
        time.sleep(20.0)
    mock_db = mock.Mock()
    mock_db.execute.side_effect = _hang
    mock_get_client.return_value = mock_db
    
    # We monkeypatch the timeout in ThreadPoolExecutor to make the test fast
    import concurrent.futures
    original_submit = concurrent.futures.ThreadPoolExecutor.submit
    def patched_result(*args, **kwargs):
        raise concurrent.futures.TimeoutError()
    mock_future = mock.Mock()
    mock_future.result = patched_result
    
    with mock.patch("concurrent.futures.ThreadPoolExecutor.submit", return_value=mock_future):
        status = dbc.verify_connection()
        assert status == "TIMEOUT"

@mock.patch("app.db.client.get_client")
def test_auth_failure_handling(mock_get_client, monkeypatch):
    monkeypatch.setenv("DRAMA_TURSO_URL", "https://test.turso.io")
    settings.DRAMA_TURSO_URL = "https://test.turso.io"
    dbc.reset_client()
    
    mock_db = mock.Mock()
    mock_db.execute.side_effect = Exception("401 Unauthorized")
    mock_get_client.return_value = mock_db
    
    status = dbc.verify_connection()
    assert status == "AUTH_FAILED"

def test_migrations_idempotency(db):
    # 'db' fixture already ran migrations once.
    # Let's run it again and see that no exceptions happen and returns empty list.
    applied = dbc.migrate()
    assert applied == []

def test_ready_db_state_unreachable(monkeypatch):
    from app.main import create_app
    from fastapi.testclient import TestClient
    
    monkeypatch.setenv("DRAMA_TURSO_URL", "https://invalid.turso.io")
    settings.DRAMA_TURSO_URL = "https://invalid.turso.io"
    dbc.reset_client()
    
    # Force _db_status to NETWORK_ERROR
    dbc._db_status = "NETWORK_ERROR"
    
    r = TestClient(create_app()).get("/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["db"] == "NETWORK_ERROR"
    assert body["ok"] is False

def test_remote_client_selection(monkeypatch):
    monkeypatch.setenv("DRAMA_TURSO_URL", "https://test.turso.io")
    settings.DRAMA_TURSO_URL = "https://test.turso.io"
    dbc.reset_client()
    ok, db_type = dbc.db_configured()
    assert ok is True
    assert db_type == "turso"

