# Douyin → YouTube Automation

Tự động tải video Douyin (qua Rcuts), tạo metadata AI, và đăng lên YouTube Shorts theo pipeline. Hỗ trợ nhiều YouTube channel (workspace), nhiều nguồn Douyin/Facebook, scheduler, và dashboard Next.js.

> Production: API `https://douyin-api.toolnet.tech` (Render) + Dashboard `https://douyin.toolnet.tech` (Vercel)

## Features

- **Manual publish**: dán link Douyin → preview → AI metadata → Publish Now
- **AI Comment Reply** (per channel): worker độc lập quét bình luận YouTube mới → AI phân loại → tạo reply → Review hoặc Auto → `comments.insert`. Dùng **prompt riêng biệt** với prompt metadata.
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
Inventory (manual, admin-triggered): PipelineSource (douyin) ──► RapidAPI JustOne get-user-video-list/v3 ──► DouyinVideo (inventory) ──► AI match → metadata → scheduler → Publication → worker → YouTube
```

### Douyin Inventory (chế độ thủ công, tiết kiệm quota)

Douyin **không còn được quét tự động** (`DOUYIN_AUTO_SCAN_ENABLED=false`); scheduler chỉ đọc Inventory để chọn video đăng. Admin tự bấm cập nhật trên dashboard:

- **Import ban đầu** (`POST /api/sources/{id}/initial-import`): phân trang đến `has_more=false`, upsert từng trang vào Inventory. Lưu cursor sau mỗi trang nên có thể **chạy tiếp** (`POST /api/sources/{id}/initial-import/resume`) khi hết quota.
- **Cập nhật video mới** (`POST /api/sources/{id}/refresh`): chỉ đọc trang 1 (mới nhất) và dừng ngay khi gặp `aweme_id` đã biết → tốn tối thiểu request.
- **Quota guard** (`GET /api/douyin/quota`): RapidAPI BASIC ~20 request/tháng (1 page = 1 request). `app_settings.rapidapi_quota_state` theo dõi số còn lại + tháng, chặn trước khi gọi khi chạm ngưỡng `RAPIDAPI_QUOTA_SAFETY_MARGIN`, và đánh dấu `quota_exhausted` khi provider trả 429/code 303.
- Xem Inventory của một source: `GET /api/sources/{id}/inventory`.

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
- `POST /api/sources/{id}/initial-import` / `/initial-import/resume` / `/refresh` → đồng bộ Inventory Douyin (thủ công)
- `GET /api/sources/{id}/inventory` / `GET /api/douyin/quota`
- `GET /api/channels/{id}/comments` / `POST /api/channels/{id}/comments/scan`
- `POST /api/channels/{id}/comments/{comment_id}/generate-reply` `/reply` `/skip`
- `GET|PATCH /api/channels/{id}/comment-reply-settings`
- `GET /api/channels/{destination_id}/sources` / `POST /api/channels/{destination_id}/sources`
- `POST /api/youtube/oauth-url?destination_id=...` → Google OAuth `https://accounts.google.com/o/oauth2/v2/auth`

### AI Comment Reply — hai prompt hoàn toàn độc lập

Mỗi YouTube destination/kênh có **hai** system prompt tách biệt, không bao giờ được merge hay fallback lẫn nhau:

| Field | Dùng cho | Ghi chú |
| --- | --- | --- |
| `prompt_override` (là `metadata_system_prompt`) | title / description / hashtags / publish metadata | **Giữ nguyên** hành vi cũ, không rename |
| `comment_reply_system_prompt` | đọc bình luận + tạo câu trả lời bình luận | Chỉ `app/ai_comment_reply.py` đọc field này |

Ràng buộc được test tự động (`backend/tests/test_comment_reply.py`):

- `app/ai_comment_reply.py` **không** được tham chiếu `prompt_override` / `metadata_profile` / `metadata_language`.
- `app/ai_metadata.py` **không** được tham chiếu `comment_reply_system_prompt`.
- Khi cả hai prompt được set khác hẳn nhau, payload gửi AI của luồng comment chỉ chứa prompt comment, và payload của luồng metadata chỉ chứa prompt metadata.

Luồng:

```
VIDEO PUBLISH   video → metadata_system_prompt → title/description/hashtags → upload
COMMENT REPLY   new comment → comment_reply_system_prompt → AI reply → comments.insert
```

Đặc điểm khác:

- **OAuth**: cần thêm scope `https://www.googleapis.com/auth/youtube.force-ssl` (giữ `youtube.upload` + `youtube.readonly`). Kênh kết nối trước thay đổi này sẽ hiện *"Reconnect required for comment replies"* (mã `YOUTUBE_SCOPE_MISSING`) — không tự giả định refresh token cũ có scope mới.
- **API**: đọc bằng `commentThreads.list`, trả lời bằng `comments.insert` với `parentId` (không dùng `commentThreads.insert`).
- **Phân loại**: POSITIVE / QUESTION / NEUTRAL / NEGATIVE / SPAM / ABUSE / SENSITIVE / SKIP. SPAM, ABUSE, SENSITIVE, SKIP luôn bị giữ lại cho người duyệt, kể cả khi cấu hình kênh cho phép.
- **Mode**: `off` / `review` (AI draft → `ready_to_reply`) / `auto` (reply trực tiếp). Lần quét đầu chỉ ingest, **không** auto-reply cả backlog.
- **Rate limit**: `comment_reply_daily_limit` (mặc định 20/ngày) và `comment_reply_min_interval_seconds` (mặc định 180s) cho từng kênh.
- **Chống trùng**: unique `youtube_comment_id`; comment đã có `youtube_reply_id` không bao giờ gửi lại; comment kẹt ở `replying` được reconcile lại với YouTube trước khi retry.
- **Worker riêng**: `Lifespan` chạy task `comment_worker_loop()` với interval `COMMENT_SCAN_INTERVAL_MINUTES`, không dùng chung task với publish worker.

## Deployment

- **Render** (`render.yaml`): `douyin-youtube-api` (Docker, `backend/Dockerfile` + `prompts/`), `douyin-dashboard` (Node). Env `RCUTS_*`, `DATABASE_URL`, `ADMIN_TOKEN`, `GOOGLE_*` set trong Render Dashboard.
- **Vercel**: Dashboard build `npm run build`, env `DOUYIN_API_URL`, `DOUYIN_ADMIN_TOKEN`, `DASHBOARD_SECRET`.

## Status Flow

`pending → downloading → uploading → published` (fail → `failed` → retry → `pending`)

## License

Private — LETAN-Media
