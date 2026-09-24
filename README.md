# Douyin → YouTube Automation

Tự động tải video Douyin (qua Rcuts), tạo metadata AI, và đăng lên YouTube Shorts theo pipeline. Hỗ trợ nhiều YouTube channel (workspace), nhiều nguồn Douyin/Facebook, scheduler, và dashboard Next.js.

> Production: API `https://douyin-api.toolnet.tech` (Render) + Dashboard `https://douyin.toolnet.tech` (Vercel)

## Features

- **Manual publish**: dán link Douyin → preview → AI metadata → Publish Now
- **Auto mode**: quét creator định kỳ (Playwright), dedupe `aweme_id`, AI Content Match 3 mức (match/borderline/mismatch), metadata, scheduler theo slot, YouTube upload
- **Shared Platform Auth**: 1 Douyin login (PlatformAccount) dùng chung cho mọi source/pipeline; Facebook stub
- **Downloader**: `Rcuts` primary (`DouYin_All.php`) → fallback (`DouYin.php`) → `yt-dlp` cuối; HTTP download MP4 + `ffprobe` validate
- **Scheduler**: daily limit, upload interval, order (oldest/newest), backlog/new ratio
- **Dashboard**: Channels, Sources, Inventory, Queue, Published, AI Profile, Settings; channel là isolated workspace

## Architecture

```
Douyin URL ──► Rcuts (primary All.php → fallback DouYin.php) ──► video_url ──► HTTP MP4 (/tmp/douyin-youtube/{job_id}.mp4) ──► yt-dlp fallback
                                          │
Manual: paste URL → /api/manual/resolve → Rcuts metadata → /api/manual/metadata (AI) → /api/channels/{id}/publish → Publication (queued) → worker
Auto: PlatformAccount(douyin) ──► PipelineSource (douyin/facebook) ──► Playwright scan ──► DouyinVideo (inventory) ──► AI match → metadata → scheduler → Publication → worker → YouTube
```

- **Frontend**: `dashboard/` Next.js 16 (App Router) → proxy `/api/[...path]` tới FastAPI, `X-Admin-Token` server-only
- **Backend**: `backend/app` FastAPI + SQLAlchemy + Supabase Postgres, `worker.py` (download → AI → upload), `monitor.py` (due scan), `scheduler.py` (slot), `youtube.py` (OAuth)
- **DB**: `pipelines` → `destinations` (YouTube) → `douyin_sources` / `pipeline_sources` → `douyin_videos` → `publications` → `video_jobs`; `platform_accounts` (global login)

## Tech Stack

- FastAPI, SQLAlchemy, psycopg, Pydantic Settings
- yt-dlp, FFmpeg, Playwright (Chromium)
- YouTube Data API (google-api-python-client, google-auth)
- PostgreSQL / Supabase, Next.js, Tailwind, Vercel, Render (Docker)

## Quick Start

```bash
git clone https://github.com/LETAN-Media/douyin-youtube.git
cd douyin-youtube/backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium  # for creator scan
cp .env.example .env  # điền DATABASE_URL, ADMIN_TOKEN, GOOGLE_*, AI_*, RCUTS_*
uvicorn app.main:app --reload --port 8000
# worker/monitor/scheduler chạy trong cùng process (lifespan)
```

Dashboard:
```bash
cd ../dashboard
cp .env.example .env.local  # DOUYIN_API_URL, DOUYIN_ADMIN_TOKEN, DASHBOARD_SECRET
npm ci && npm run dev  # http://localhost:3000
```

## Environment

Backend `backend/.env` (không commit):

```
DATABASE_URL=postgresql+psycopg://...
ADMIN_TOKEN=...
PUBLIC_BASE_URL=https://douyin-api.toolnet.tech
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
CORS_ORIGINS=https://douyin.toolnet.tech
AI_ENABLED=true
AI_BASE_URL=https://api.toolnet.tech/v1
AI_API_KEY=...
AI_MODEL=youtube-douyin

# Rcuts (centralized, không dùng /root/shortcut-douyin/rcuts.env)
RCUTS_API=http://api.rcuts.com/Video/DouYin.php
RCUTS_PRIMARY_API=http://api.rcuts.com/Video/DouYin_All.php
RCUTS_FALLBACK_API=http://api.rcuts.com/Video/DouYin.php

# Optional cookies fallback (global PlatformAccount là chính)
DOUYIN_COOKIES_B64=
```

Root `.env` (`/root/douyin-youtube/.env`) chỉ chứa 3 biến `RCUTS_*` để đồng bộ local, production Render đọc từ Environment Variables.

Dashboard `.env`:
```
DOUYIN_API_URL=https://douyin-api.toolnet.tech
DOUYIN_ADMIN_TOKEN=...
DASHBOARD_SECRET=...
```

## API (yêu cầu `X-Admin-Token`)

- `POST /api/manual/resolve` `{input}` → Rcuts video/profile
- `POST /api/manual/metadata` `{source_url, caption, destination_ids}` → AI title/desc/hashtags
- `POST /api/channels/{destination_id}/publish` / `POST /api/manual/publish` → Publication queued
- `GET /api/platform-accounts` / `POST /api/platform-accounts/douyin` / `POST /api/platform-accounts/douyin/test`
- `GET /api/pipelines/{id}/sources` / `POST /api/pipelines/{id}/sources` `{platform, source_url, source_name}`
- `GET /api/channels/{destination_id}/sources` / `POST /api/channels/{destination_id}/sources`
- `POST /api/youtube/oauth-url?destination_id=...` → Google OAuth `https://accounts.google.com/o/oauth2/v2/auth`

## Deployment

- **Render** (`render.yaml`): `douyin-youtube-api` (Docker, `backend/Dockerfile` + `prompts/`), `douyin-dashboard` (Node). Env `RCUTS_*`, `DATABASE_URL`, `ADMIN_TOKEN`, `GOOGLE_*` set trong Render Dashboard.
- **Vercel**: Dashboard build `npm run build`, env `DOUYIN_API_URL`, `DOUYIN_ADMIN_TOKEN`, `DASHBOARD_SECRET`.

## Status Flow

`pending → downloading → uploading → published` (fail → `failed` → retry → `pending`)

## License

Private — LETAN-Media
