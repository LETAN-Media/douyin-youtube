# Douyin → YouTube Automation

Components:

- FastAPI
- PostgreSQL / Supabase
- yt-dlp
- FFmpeg
- YouTube Data API OAuth
- Background queue worker
- Vercel static dashboard

Statuses:

pending
→ downloading
→ uploading
→ published

Failures become:

failed
→ retry
→ pending
