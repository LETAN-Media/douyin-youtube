# backend\_youtube

Independent, production-grade backend for **YouTube Sources → Facebook Fanpage**
publishing, built on **Neon PostgreSQL** (SQLAlchemy 2.x async + asyncpg + Alembic).
This is the reverse direction of `backend_facebook/` (which does Facebook → YouTube);
no business logic is shared.

## Architecture

```
YouTube (Data API v3)  -->  YouTubeVideo records  -->  MediaFile (yt-dlp/ffmpeg or FastSaver)
                          -->  AI caption (ToolNet)  -->  PublishQueue  -->  Facebook Graph API
                          -->  PublishSchedule / QuotaState  -->  PublicationHistory
```

Background workers (`app/services/workers.py`):
- `scheduler` — generates per-day publish slots and schedules pending queue items.
- `publish_worker` — atomically claims scheduled items (`SKIP LOCKED`), publishes to the
  configured Facebook Page, records history, and retries with backoff.
- `ai_worker` — enriches queued items with AI-generated captions.

## Database

- Production: Neon PostgreSQL via `DATABASE_URL` (PostgreSQL, `sslmode=require`, connection pool, statement/lock timeouts).
- Tests: SQLite (aiosqlite) — the test DB is dialect-portable; idempotent jobs are claimed with a
  portable conditional `UPDATE` plus `SKIP LOCKED` guarded by dialect detection.
- Schema migrations live in `alembic/versions/`. Apply with:
  ```
  alembic upgrade head
  ```

### Idempotency / recovery
- `publication_history` has a unique constraint on `(pipeline_id, youtube_video_id, facebook_page_id)` —
  prevents double-publishing the same YouTube video to the same Facebook page.
- `publish_queue` rows carry `reservation_token` + `reservation_expires_at`; stale claims are
  reclaimed (`SKIP LOCKED` on Postgres). Workers are recoverable after restart.

## Configuration

Copy `.env.example` to `.env` and fill in secrets:

| Variable | Description |
| --- | --- |
| `DATABASE_URL` | Neon PostgreSQL connection string. |
| `ADMIN_TOKEN` | Bearer token for admin endpoints; rotate from `CHANGE_ME...`. |
| `YOUTUBE_DATA_API_KEY` | YouTube Data API v3 key (for source scanning). |
| `FACEBOOK_APP_ID/SECRET` | Meta app credentials (OAuth + token refresh). |
| `FACEBOOK_PAGE_ACCESS_TOKEN` | Fallback page token; per-page tokens are encrypted in the DB. |
| `TOKEN_ENCRYPTION_KEY` | Fernet key for encrypting stored Page Access Tokens. |
| `TOOLNET_AI_ENABLED/BASE_URL/API_KEY/MODEL` | ToolNet AI endpoint. |
| `FASTSAVER_API_KEY` | FastSaver media fallback adapter. |

`ADMIN_TOKEN`, `CORS_ORIGINS`, worker toggles, pool/timeout settings are consumed from `app/config.py`.

## API

OpenAPI docs: `/api/youtube-fb/docs`. Health: `/api/youtube-fb/health`.

All routes are under `/api/youtube-fb/` and proxied through the dashboard (see `dashboard/app/api/youtube-fb/*`).

## Run locally

```bash
cp .env.example .env
# edit .env, then:
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload
```

## Tests

```bash
.venv/bin/pytest -q
```

Tests run against an isolated SQLite database and **never** touch Neon production.

## Docker

```bash
docker build -t backend-youtube .
docker run -p 8000:8000 --env-file .env backend-youtube
```
