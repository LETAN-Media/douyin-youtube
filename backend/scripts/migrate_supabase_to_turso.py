#!/usr/bin/env python3
"""Migrate all data from Supabase PostgreSQL to Turso/libSQL."""
import json
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

load_dotenv('.env')

SUPABASE_URL = os.environ.get('DATABASE_URL')
TURSO_URL = os.environ.get('TURSO_URL')
TURSO_TOKEN = os.environ.get('TURSO_TOKEN')

if not SUPABASE_URL or not TURSO_URL or not TURSO_TOKEN:
    print("DATABASE_URL, TURSO_URL, and TURSO_TOKEN must be set")
    sys.exit(1)

# Normalize Supabase URL for SQLAlchemy
if SUPABASE_URL.startswith("postgresql://"):
    SUPABASE_URL = SUPABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
elif SUPABASE_URL.startswith("postgres://"):
    SUPABASE_URL = SUPABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)

TURSO_SQLITE_URL = f"sqlite+libsql://{TURSO_URL.replace('https://', '').replace('http://', '')}?secure=1"

supabase_engine = create_engine(SUPABASE_URL, pool_pre_ping=True)
turso_engine = create_engine(TURSO_SQLITE_URL, connect_args={"auth_token": TURSO_TOKEN})


def serialize_value(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.astimezone(timezone.utc).isoformat()
    if isinstance(val, (list, dict)):
        return json.dumps(val)
    return val


def get_supabase_tables(conn):
    result = conn.execute(text("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """))
    return [r[0] for r in result.fetchall()]


def get_supabase_rows(conn, table):
    result = conn.execute(text(f'SELECT * FROM {table}'))
    cols = [desc[0] for desc in result.cursor.description]
    rows = []
    for row in result.fetchall():
        data = {}
        for c, v in zip(cols, row):
            data[c] = serialize_value(v)
        rows.append(data)
    return cols, rows


def insert_rows_turso(conn, table, cols, rows, batch_size=50):
    if not rows:
        return 0
    reserved = {'order', 'group', 'index', 'key', 'table', 'select', 'from', 'where', 'join', 'on', 'set'}
    total = 0
    for batch_start in range(0, len(rows), batch_size):
        batch = rows[batch_start:batch_start + batch_size]
        val_lists = []
        all_params = {}
        for idx, row in enumerate(batch):
            placeholders = []
            for i, c in enumerate(cols):
                pname = f'p{batch_start + idx}_{i}'
                placeholders.append(f':{pname}')
                all_params[pname] = row[c]
            val_lists.append(f'({",".join(placeholders)})')
        col_list = ', '.join([f'"{c}"' if c.lower() in reserved else c for c in cols])
        sql = f'INSERT OR REPLACE INTO {table} ({col_list}) VALUES {",".join(val_lists)}'
        conn.execute(text(sql), all_params)
        total += len(batch)
    return total


def migrate():
    print("Connecting to Supabase...")
    with supabase_engine.connect() as src:
        print("Connecting to Turso...")
        with turso_engine.connect() as dst:
            dst.execute(text("PRAGMA foreign_keys = OFF"))
            dst.commit()

            tables = get_supabase_tables(src)
            print(f"Found {len(tables)} tables in Supabase")

            insert_order = [
                'workspaces',
                'users',
                'pipelines',
                'platform_accounts',
                'destinations',
                'pipeline_sources',
                'douyin_sources',
                'douyin_videos',
                'publications',
                'video_jobs',
                'youtube_research_runs',
                'youtube_research_items',
                'youtube_channel_dna',
                'youtube_content_fingerprints',
                'youtube_comments',
                'youtube_channel_analytics_daily',
                'youtube_video_analytics_daily',
                'youtube_dna_suggestions',
                'youtube_performance_snapshots',
                'youtube_daily_publish_overrides',
                'oauth_states',
                'workspace_members',
                'user_sessions',
                'app_settings',
                'douyin_sessions',
            ]
            ordered = [t for t in insert_order if t in tables]
            remaining = [t for t in tables if t not in ordered]
            ordered.extend(remaining)

            total = 0
            for table in ordered:
                count = src.execute(text(f'SELECT COUNT(*) FROM {table}')).fetchone()[0]
                if count == 0:
                    print(f"  {table}: 0 rows (skipped)")
                    continue
                print(f"  {table}: {count} rows -> migrating...")
                cols, rows = get_supabase_rows(src, table)
                inserted = insert_rows_turso(dst, table, cols, rows)
                dst.commit()
                print(f"  {table}: {inserted} rows migrated")
                total += inserted

            print(f"\nTotal rows migrated: {total}")


if __name__ == '__main__':
    migrate()
