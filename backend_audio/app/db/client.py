"""Database client: local SQLite fallback + Turso via Hrana HTTPS (urllib).

libsql_client's sync execute() hangs in some sandboxed networks, so the
remote path uses plain Hrana /v2/pipeline POSTs (proven against the real
Turso hosts). Same cursor interface for both paths:
execute(sql, params) with ? or :named placeholders, fetchone()/fetchall(),
row["col"] and row[idx], commit().
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import urllib.request
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger("backend-audio.db")

SCHEMA_VERSION_TABLE = "audio_schema_migrations"


class Row(dict):
    def __init__(self, cols: list[str], values: list[Any]):
        super().__init__(zip(cols, values))
        self._ordered = list(values)

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return self._ordered[key]
        return super().__getitem__(key)


class Cursor:
    def __init__(self, cols: list[str], rows: list[list[Any]]):
        self._rows = [Row(cols, r) for r in rows]

    def fetchone(self) -> Row | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[Row]:
        return list(self._rows)


def _to_positional(sql: str, parameters: Any) -> tuple[str, list[Any]]:
    if isinstance(parameters, dict):
        names = re.findall(r":([A-Za-z_][A-Za-z0-9_]*)", sql)
        args: list[Any] = []
        for i, name in enumerate(names, 1):
            sql = sql.replace(":" + name, f"?{i}", 1)
            args.append(parameters[name])
        return sql, args
    params = list(parameters or [])
    out: list[str] = []
    idx = 0
    for ch in sql:
        if ch == "?":
            idx += 1
            out.append(f"?{idx}")
        else:
            out.append(ch)
    return "".join(out), params


def _hrana_arg(value: Any) -> dict[str, Any]:
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": str(int(value))}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    return {"type": "text", "value": str(value)}


class HranaDatabase:
    """Turso remote over HTTPS. Stateless per call (no hanging websocket)."""

    def __init__(self, url: str, token: str):
        url = url.strip()
        if url.startswith("libsql://"):
            url = "https://" + url[len("libsql://"):]
        self._endpoint = url.rstrip("/") + "/v2/pipeline"
        self._token = token

    def execute(self, sql: str, parameters: Any = ()) -> Cursor:
        sql, args = _to_positional(sql, parameters)
        payload = {
            "requests": [{
                "type": "execute",
                "stmt": {"sql": sql, "args": [_hrana_arg(v) for v in args]},
            }],
        }
        req = urllib.request.Request(
            self._endpoint,
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.load(resp)
        res = body["results"][0]
        if res.get("type") != "ok":
            raise RuntimeError(f"Turso error: {res}")
        out = res["response"]["result"]
        cols = [c["name"] for c in out.get("cols", [])]
        decl = [c.get("decltype", "") for c in out.get("cols", [])]
        rows = [[c.get("value") for c in r] for r in out.get("rows", [])]
        for row in rows:
            for i, value in enumerate(row):
                if isinstance(value, str) and decl[i] == "INTEGER":
                    try:
                        row[i] = int(value)
                    except ValueError:
                        pass
        return Cursor(cols, rows)

    def executemany(self, sql: str, seq: Any) -> None:
        for params in seq:
            self.execute(sql, params)

    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass


class LocalDatabase:
    def __init__(self, path: str):
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(p), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()

    def execute(self, sql: str, parameters: Any = ()) -> Cursor:
        if isinstance(parameters, dict):
            params: Any = parameters
        else:
            params = list(parameters or [])
            # back-convert ?N to ? for sqlite3
            sql = re.sub(r"\?\d+", "?", sql)
        with self._lock:
            cur = self._conn.execute(sql, params)
            cols = [d[0] for d in cur.description] if cur.description else []
            rows = [list(r) for r in cur.fetchall()]
        return Cursor(cols, rows)

    def executemany(self, sql: str, seq: Any) -> None:
        with self._lock:
            self._conn.executemany(sql, seq)

    def commit(self) -> None:
        with self._lock:
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


_client: Any = None
_lock = threading.Lock()


def get_client() -> Any:
    global _client
    with _lock:
        if _client is None:
            url = (settings.AUDIO_TURSO_URL or "").strip()
            if url and not url.startswith("file:"):
                _client = HranaDatabase(url, settings.AUDIO_TURSO_TOKEN or "")
            else:
                # Production must never silently fall back to ephemeral SQLite.
                if (settings.APP_ENV or "").strip().lower() == "production":
                    raise RuntimeError(
                        "AUDIO_TURSO_URL is missing in production; refusing "
                        "ephemeral SQLite fallback.")
                path = (
                    Path(url[len("file:"):])
                    if url.startswith("file:")
                    else Path(settings.AUDIO_DB_PATH)
                )
                _client = LocalDatabase(str(path))
        return _client


def reset_client() -> None:
    global _client
    with _lock:
        if _client is not None:
            try:
                _client.close()
            except Exception:
                pass
            _client = None


def db_configured() -> tuple[bool, str]:
    url = (settings.AUDIO_TURSO_URL or "").strip()
    if not url or url.startswith("file:"):
        return True, "sqlite"
    return True, "turso"
