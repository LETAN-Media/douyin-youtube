"""Drama pipeline / source / series / episode repositories (SQLite)."""

import json
import uuid
from typing import Any

import sqlite3

from ..client import get_client


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_pipeline(r: Any) -> dict[str, Any]:
    return {
        "id": r["id"], "name": r["name"], "slug": r["slug"],
        "enabled": bool(r["enabled"]), "auto_publish": bool(r["auto_publish"]),
        "created_at": r["created_at"], "updated_at": r["updated_at"],
    }


def _row_to_source(r: Any) -> dict[str, Any]:
    return {
        "id": r["id"], "pipeline_id": r["pipeline_id"],
        "provider": r["provider"], "source_url": r["source_url"],
        "external_series_id": r["external_series_id"], "name": r["name"],
        "enabled": bool(r["enabled"]), "last_scan_at": r["last_scan_at"],
        "scan_cursor": r["scan_cursor"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
    }


def _row_to_series(r: Any) -> dict[str, Any]:
    try:
        metadata = json.loads(r["metadata_json"]) if r["metadata_json"] else {}
    except Exception:
        metadata = {}
    return {
        "id": r["id"], "source_id": r["source_id"], "provider": r["provider"],
        "external_series_id": r["external_series_id"], "title": r["title"],
        "description": r["description"], "thumbnail_url": r["thumbnail_url"],
        "total_episodes": r["total_episodes"], "metadata": metadata,
        "created_at": r["created_at"], "updated_at": r["updated_at"],
    }


def _row_to_episode(r: Any) -> dict[str, Any]:
    return {
        "id": r["id"], "series_id": r["series_id"], "provider": r["provider"],
        "external_episode_id": r["external_episode_id"],
        "episode_number": r["episode_number"], "title": r["title"],
        "source_url": r["source_url"], "thumbnail_url": r["thumbnail_url"],
        "duration": r["duration"], "status": r["status"],
        "published_at": r["published_at"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
    }


# ---------- pipelines ----------


def create_pipeline(*, name: str, slug: str | None = None, enabled: bool = True,
                    auto_publish: bool = True) -> dict[str, Any]:
    conn = get_client()
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("Pipeline name must not be empty.")
    clean_slug = (slug or "").strip().lower().replace(" ", "-") or None
    if not clean_slug:
        import re

        base = re.sub(r"[^a-z0-9]+", "-", clean_name.lower()).strip("-") or "pipeline"
        clean_slug = base
        n = 1
        while conn.execute(
            "SELECT 1 FROM drama_pipelines WHERE slug = ?", (clean_slug,)
        ).fetchone():
            n += 1
            clean_slug = f"{base}-{n}"
    pid = _new_id("dpl")
    try:
        conn.execute(
            "INSERT INTO drama_pipelines (id, name, slug, enabled, auto_publish) "
            "VALUES (?, ?, ?, ?, ?)",
            (pid, clean_name, clean_slug, 1 if enabled else 0, 1 if auto_publish else 0),
        )
        conn.commit()
    except Exception as exc:
        raise ValueError(f"Pipeline slug already exists: {clean_slug}") from exc
    return get_pipeline(pid)  # type: ignore[return-value]



def get_pipeline(pipeline_id: str) -> dict[str, Any] | None:
    row = get_client().execute(
        "SELECT * FROM drama_pipelines WHERE id = ?", (pipeline_id,)
    ).fetchone()
    return _row_to_pipeline(row) if row else None


def list_pipelines(*, enabled_only: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT * FROM drama_pipelines"
    if enabled_only:
        sql += " WHERE enabled = 1"
    sql += " ORDER BY created_at ASC, id ASC"
    return [_row_to_pipeline(r) for r in get_client().execute(sql).fetchall()]


# ---------- sources ----------


def create_source(*, pipeline_id: str, provider: str = "rapidix",
                  source_url: str | None = None,
                  external_series_id: str | None = None,
                  name: str | None = None,
                  enabled: bool = True) -> dict[str, Any]:
    if get_pipeline(pipeline_id) is None:
        raise ValueError(f"Pipeline not found: {pipeline_id}")
    if external_series_id:
        existing = get_client().execute(
            "SELECT * FROM drama_sources WHERE pipeline_id = ? AND provider = ? AND external_series_id = ?",
            (pipeline_id, provider, external_series_id),
        ).fetchone()
        if existing:
            row_id = existing[0] if isinstance(existing, tuple) else existing["id"]
            if name is not None or enabled is not None:
                get_client().execute(
                    "UPDATE drama_sources SET name = COALESCE(?, name), enabled = ? WHERE id = ?",
                    (name, 1 if enabled else 0, row_id),
                )
                get_client().commit()
            updated = get_client().execute("SELECT * FROM drama_sources WHERE id = ?", (row_id,)).fetchone()
            return _row_to_source(updated or existing)
    sid = _new_id("dsrc")
    get_client().execute(
        "INSERT INTO drama_sources (id, pipeline_id, provider, source_url, "
        "external_series_id, name, enabled) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (sid, pipeline_id, provider, source_url, external_series_id, name,
         1 if enabled else 0),
    )
    get_client().commit()
    row = get_client().execute("SELECT * FROM drama_sources WHERE id = ?", (sid,)).fetchone()
    assert row is not None
    return _row_to_source(row)


def get_source(source_id: str) -> dict[str, Any] | None:
    row = get_client().execute(
        "SELECT * FROM drama_sources WHERE id = ?", (source_id,)
    ).fetchone()
    return _row_to_source(row) if row else None


def list_sources(pipeline_id: str) -> list[dict[str, Any]]:
    return [
        _row_to_source(r)
        for r in get_client().execute(
            "SELECT * FROM drama_sources WHERE pipeline_id = ? "
            "ORDER BY created_at ASC, id ASC",
            (pipeline_id,),
        ).fetchall()
    ]


def touch_source(source_id: str, *, scan_cursor: str | None = None) -> None:
    get_client().execute(
        "UPDATE drama_sources SET last_scan_at = ?, scan_cursor = ?, "
        "updated_at = ? WHERE id = ?",
        (scan_cursor if scan_cursor is not None else _now(), scan_cursor,
         _now(), source_id),
    )
    get_client().commit()


# ---------- series ----------


def upsert_series(*, source_id: str, provider: str, external_series_id: str,
                  title: str | None = None, description: str | None = None,
                  thumbnail_url: str | None = None,
                  total_episodes: int | None = None,
                  metadata: dict | None = None) -> tuple[dict[str, Any], bool]:
    """Returns (row, created). Matches on (provider, external_series_id)."""
    conn = get_client()
    row = conn.execute(
        "SELECT * FROM drama_series WHERE provider = ? AND external_series_id = ?",
        (provider, external_series_id),
    ).fetchone()
    if row is None:
        sid = _new_id("dser")
        conn.execute(
            "INSERT INTO drama_series (id, source_id, provider, external_series_id, "
            "title, description, thumbnail_url, total_episodes, metadata_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, source_id, provider, external_series_id, title, description,
             thumbnail_url, total_episodes, json.dumps(metadata or {})),
        )
        conn.commit()
        created = True
    else:
        sid = row["id"]
        meta_str = json.dumps(metadata) if metadata is not None else None
        conn.execute(
            "UPDATE drama_series SET source_id = ?, "
            "title = COALESCE(?, title), "
            "description = COALESCE(?, description), "
            "thumbnail_url = COALESCE(?, thumbnail_url), "
            "total_episodes = COALESCE(?, total_episodes), "
            "metadata_json = COALESCE(?, metadata_json), "
            "updated_at = ? WHERE id = ?",
            (source_id, title, description, thumbnail_url, total_episodes,
             meta_str, _now(), sid),
        )
        conn.commit()
        created = False
    fresh = conn.execute("SELECT * FROM drama_series WHERE id = ?", (sid,)).fetchone()
    assert fresh is not None
    return _row_to_series(fresh), created


def get_series(series_id: str) -> dict[str, Any] | None:
    row = get_client().execute(
        "SELECT * FROM drama_series WHERE id = ?", (series_id,)
    ).fetchone()
    return _row_to_series(row) if row else None


def list_series(*, query: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
    conn = get_client()
    where_clauses = []
    params = []
    
    if query:
        where_clauses.append("t.title LIKE ?")
        params.append(f"%{query}%")
        
    where_sql = " AND ".join(where_clauses)
    if where_sql:
        where_sql = f"WHERE {where_sql}"
        
    total_row = conn.execute(
        f"SELECT COUNT(*) FROM drama_series t {where_sql}", tuple(params)
    ).fetchone()
    total = total_row[0] if total_row else 0
    
    params.extend([limit, offset])
    rows = conn.execute(
        f"SELECT t.*, s.pipeline_id FROM drama_series t "
        f"LEFT JOIN drama_sources s ON s.id = t.source_id "
        f"{where_sql} "
        "ORDER BY t.created_at DESC LIMIT ? OFFSET ?",
        tuple(params)
    ).fetchall()
    
    res = []
    for r in rows:
        d = _row_to_series(r)
        if "pipeline_id" in r.keys():
            d["pipeline_id"] = r["pipeline_id"]
        res.append(d)
        
    return res, total


# ---------- episodes ----------


def upsert_episode(*, series_id: str, provider: str,
                   external_episode_id: str | None,
                   episode_number: int, title: str | None = None,
                   source_url: str | None = None,
                   thumbnail_url: str | None = None,
                   duration: float | None = None) -> tuple[dict[str, Any], str]:
    """Returns (row, outcome) where outcome is inserted|existing|updated.

    Dedupe: (provider, external_episode_id) first; fallback
    (series_id, episode_number) when the provider id is missing.
    """
    conn = get_client()
    row = None
    if external_episode_id:
        row = conn.execute(
            "SELECT * FROM drama_episodes WHERE provider = ? AND external_episode_id = ?",
            (provider, external_episode_id),
        ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT * FROM drama_episodes WHERE series_id = ? AND episode_number = ?",
            (series_id, episode_number),
        ).fetchone()
    if row is None:
        eid = _new_id("dep")
        conn.execute(
            "INSERT INTO drama_episodes (id, series_id, provider, external_episode_id, "
            "episode_number, title, source_url, thumbnail_url, duration, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'new')",
            (eid, series_id, provider, external_episode_id, episode_number,
             title, source_url, thumbnail_url, duration),
        )
        conn.commit()
        fresh = conn.execute(
            "SELECT * FROM drama_episodes WHERE id = ?", (eid,)
        ).fetchone()
        assert fresh is not None
        return _row_to_episode(fresh), "inserted"
    current = _row_to_episode(row)
    changed = (
        (title is not None and title != current["title"])
        or (source_url is not None and source_url != current["source_url"])
        or (thumbnail_url is not None and thumbnail_url != current["thumbnail_url"])
        or (duration is not None and duration != current["duration"])
    )
    if changed:
        conn.execute(
            "UPDATE drama_episodes SET title = COALESCE(?, title), "
            "source_url = COALESCE(?, source_url), "
            "thumbnail_url = COALESCE(?, thumbnail_url), "
            "duration = COALESCE(?, duration), updated_at = ? WHERE id = ?",
            (title, source_url, thumbnail_url, duration, _now(), current["id"]),
        )
        conn.commit()
        fresh = conn.execute(
            "SELECT * FROM drama_episodes WHERE id = ?", (current["id"],)
        ).fetchone()
        assert fresh is not None
        return _row_to_episode(fresh), "updated"
    return current, "existing"


def list_episodes(series_id: str, *, status: str | None = None,
                  limit: int = 500, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
    """Strict episode_number ASC ordering — never random."""
    where = "series_id = ?"
    params: list[Any] = [series_id]
    if status:
        where += " AND status = ?"
        params.append(status)
    total = get_client().execute(
        f"SELECT COUNT(*) FROM drama_episodes WHERE {where}", params
    ).fetchone()[0]
    rows = get_client().execute(
        f"SELECT * FROM drama_episodes WHERE {where} "
        "ORDER BY episode_number ASC, id ASC LIMIT ? OFFSET ?",
        (*params, max(1, min(limit, 1000)), max(0, offset)),
    ).fetchall()
    return [_row_to_episode(r) for r in rows], total


def count_episodes_by_status(series_id: str) -> dict[str, int]:
    rows = get_client().execute(
        "SELECT status, COUNT(*) FROM drama_episodes WHERE series_id = ? GROUP BY status",
        (series_id,),
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def upsert_discovery_cache_items(items: list[dict[str, Any]]) -> None:
    """Store live discovery series metadata into persistent LKG cache.
    Never stores signed playback/video URLs.
    """
    if not items:
        return
    client = get_client()
    now_str = _now()
    for item in items:
        provider = (item.get("provider") or "").strip()
        ext_id = str(item.get("external_series_id") or "").strip()
        if not provider or not ext_id:
            continue
        client.execute(
            """
            INSERT INTO drama_discovery_cache
                (provider, external_series_id, title, description, thumbnail_url, total_episodes, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider, external_series_id) DO UPDATE SET
                title = excluded.title,
                description = excluded.description,
                thumbnail_url = excluded.thumbnail_url,
                total_episodes = excluded.total_episodes,
                fetched_at = excluded.fetched_at
            """,
            (
                provider,
                ext_id,
                item.get("title"),
                item.get("description"),
                item.get("thumbnail_url"),
                item.get("total_episodes"),
                now_str,
            ),
        )
    client.commit()


def get_discovery_cache_items(
    *,
    provider: str = "all",
    query: str = "",
    limit: int = 20,
    max_age_hours: int = 24,
) -> list[dict[str, Any]]:
    """Retrieve items from persistent LKG cache within max_age_hours."""
    from datetime import datetime, timezone, timedelta
    client = get_client()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")

    sql = "SELECT provider, external_series_id, title, description, thumbnail_url, total_episodes, fetched_at FROM drama_discovery_cache WHERE fetched_at >= ?"
    params: list[Any] = [cutoff]

    norm_provider = (provider or "all").strip().lower()
    if norm_provider != "all":
        sql += " AND provider = ?"
        params.append(norm_provider)

    norm_query = (query or "").strip()
    if norm_query:
        sql += " AND (title LIKE ? OR description LIKE ?)"
        pattern = f"%{norm_query}%"
        params.extend([pattern, pattern])

    sql += " ORDER BY fetched_at DESC LIMIT ?"
    params.append(max(1, limit))

    cursor = client.execute(sql, params)
    rows = cursor.fetchall()
    out = []
    for r in rows:
        out.append({
            "provider": r["provider"],
            "external_series_id": r["external_series_id"],
            "title": r["title"],
            "description": r["description"],
            "thumbnail_url": r["thumbnail_url"],
            "total_episodes": r["total_episodes"],
        })
    return out


def upsert_discovery_snapshot(
    *,
    cache_key: str,
    provider: str,
    query: str = "",
    limit_value: int,
    items: list[dict[str, Any]],
    provider_status: dict[str, Any] | None = None,
    fetched_at: str | None = None,
) -> None:
    """Persist or update an entire discovery result set snapshot."""
    client = get_client()
    now_str = _now()
    fetch_str = fetched_at or now_str
    items_json = json.dumps(items)
    status_json = json.dumps(provider_status) if provider_status is not None else None

    client.execute(
        """
        INSERT INTO drama_discovery_snapshots
            (cache_key, provider, query, limit_value, items_json, provider_status_json, fetched_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(cache_key) DO UPDATE SET
            provider = excluded.provider,
            query = excluded.query,
            limit_value = excluded.limit_value,
            items_json = excluded.items_json,
            provider_status_json = excluded.provider_status_json,
            fetched_at = excluded.fetched_at,
            updated_at = excluded.updated_at
        """,
        (
            cache_key,
            provider,
            query,
            limit_value,
            items_json,
            status_json,
            fetch_str,
            now_str,
        ),
    )
    client.commit()


def get_discovery_snapshot(cache_key: str) -> dict[str, Any] | None:
    """Retrieve discovery snapshot by cache_key."""
    client = get_client()
    cursor = client.execute(
        "SELECT cache_key, provider, query, limit_value, items_json, provider_status_json, fetched_at, updated_at "
        "FROM drama_discovery_snapshots WHERE cache_key = ?",
        (cache_key,),
    )
    row = cursor.fetchone()
    if not row:
        return None

    def _get(key: str, idx: int):
        try:
            return row[key]
        except Exception:
            return row[idx]

    raw_items = _get("items_json", 4)
    raw_status = _get("provider_status_json", 5)
    try:
        items = json.loads(raw_items) if raw_items else []
    except Exception:
        items = []
    try:
        provider_status = json.loads(raw_status) if raw_status else {}
    except Exception:
        provider_status = {}

    return {
        "cache_key": _get("cache_key", 0),
        "provider": _get("provider", 1),
        "query": _get("query", 2),
        "limit_value": _get("limit_value", 3),
        "items": items,
        "provider_status": provider_status,
        "fetched_at": _get("fetched_at", 6),
        "updated_at": _get("updated_at", 7),
    }

