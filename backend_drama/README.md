# backend-drama — Series/Episode Inventory (Phase 1)

FastAPI service that inventories short-drama series and episodes from the
RapidIX provider (RapidAPI marketplace, ReelShort unofficial). **Phase 1
only**: catalog + scan. No OAuth, no AI, no scheduler, no publisher, no
YouTube uploads, no media downloads, no dashboard UI.

## Layout

- `app/main.py` — app factory, router wiring
- `app/config.py` — env-driven settings (no secrets in code)
- `app/auth.py` — `X-Admin-Token` guard
- `app/db/client.py` — SQLite + versioned idempotent migrations
- `app/db/repositories/drama.py` — pipelines/sources/series/episodes
- `app/models/drama.py` — provider-agnostic normalized models
- `app/services/rapidix.py` — provider adapter (typed errors, bounded retries)
- `app/services/scanner.py` — scan_source (no downloads, incremental)
- `app/routes/` — health, pipelines, sources, series, inventory

## Run locally

```bash
cd backend_drama
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill DRAMA_ADMIN_TOKEN etc.
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Health: `GET /health`. Readiness: `GET /ready` (never calls the provider).

## Provider endpoints

The RapidIX listing exposes Search / All Episodes / Episode Details, but
exact paths are NOT hardcoded. Copy them from the provider's RapidAPI
playground code snippets into:

- `RAPIDIX_SEARCH_PATH`
- `RAPIDIX_EPISODES_PATH`
- `RAPIDIX_EPISODE_PATH`

Until set, provider calls refuse with `NOT_CONFIGURED` so no quota is
burned guessing. Live calls were deliberately NOT tested in Phase 1.

## Ordering & dedupe

- Inventory is always `episode_number ASC` — the future scheduler must walk
  in order, never random.
- Dedupe on `(provider, external_episode_id)`, fallback
  `(series_id, episode_number)` when the provider id is missing.

## Tests

```bash
pytest tests/ -q
```

No production keys in tests. No live provider calls in tests.
