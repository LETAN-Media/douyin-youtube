# backend_audio

Facebook Reels → audio → loop video (+logo) → YouTube. FastAPI + Turso + R2.

## Quick start (local)

```bash
cd backend_audio
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill values, never commit .env
AUDIO_DB_PATH=/tmp/backend_audio.sqlite3 AUDIO_TURSO_URL="" \
  python3 -m pytest tests -q
uvicorn app.main:app --port 8080
```

## Deploy (Northflank)

- Build context: `backend_audio`, Dockerfile: `backend_audio/Dockerfile`, port `8080`.
- Health: `/health`, readiness: `/ready`.
- Domain: `audio-api.toolnet.tech`.
- Env: see `.env.example`. OAuth callback registered in Google Cloud:
  `https://audio-api.toolnet.tech/api/audio/youtube/oauth/callback`
- Persistent state lives in Turso/R2 only. One worker (`AUDIO_WORKER_CONCURRENCY=1`).

## Flow

Facebook URL → SnapVideo resolve → stream download → ffprobe → audio extract
→ R2 background (random, no immediate repeat) → optional JianYing SRT
(chunks 8 min, offset-merge) → single-pass ffmpeg loop+logo →
per-pipeline AI metadata → resumable YouTube upload (public) →
optional captions upload → publication record → temp cleanup.

## Benchmark (720p, veryfast, threads=2, VPS 8 Oct 2026)

| Audio | Render time | Peak RAM | Output | Duration check |
|-------|------------|----------|--------|----------------|
| 5 min | 2m53s | 190 MB | 8.9 MB | exact |
| 30 min | 16m26s | 201 MB | 53 MB | 1800.01s ✓ |
| 60 min | 34m49s | 205 MB | 106 MB | 3600.02s ✓ |

~0.57x realtime, single-pass loop+logo, no black tail. Fits small compute.

## Notes

- DB over Hrana HTTPS (urllib) — no libsql client dependency.
- AI disclosure: YouTube Data API has no synthetic-content flag;
  publish returns `AI_DISCLOSURE_REQUIRES_MANUAL_REVIEW` → set it in Studio.
- Scanner reports honest counts; no listing provider is configured yet
  (`SCAN_API_MISSING`), inventory import API covers manual seeding.
