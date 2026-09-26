# Northflank Deployment Configuration for douyin-youtube

## Project Discovery (Manual - API token invalid)

**Expected Project State:**
- Project: `douyin-youtube` (or similar)
- Team: `douyin-feed-apis-team` (entityInternalId from token)
- Region: Likely `eu-west-1` or `us-east-1`
- Repo: `LETAN-Media/douyin-youtube`
- Branch: `main`
- Build Context: `/backend`
- Dockerfile: `/backend/Dockerfile`
- Service Name: `douyin-youtube`
- Compute Plan: `nf-compute-20` (2 vCPU, 4GB RAM)
- Instances: 1
- Port: 8000 (HTTP public)
- Health Check: `/health`

**Note:** Northflank API token provided (`nf-...`) returns 401 Unauthorized on all endpoints. This appears to be a team token without API permissions. A Personal Access Token (PAT) with appropriate scopes is needed for programmatic access.

---

## ENV Variable Audit

### REQUIRED (Production Must-Have)

| Variable | Source | Description |
|----------|--------|-------------|
| `DATABASE_URL` | backend/.env | Supabase PostgreSQL connection string (pooled) |
| `ADMIN_TOKEN` | backend/.env | Admin API authentication token |
| `PUBLIC_BASE_URL` | backend/.env | Production API base URL (e.g., `https://douyin-api.toolnet.tech`) |
| `GOOGLE_CLIENT_ID` | backend/.env | Google OAuth client ID for YouTube |
| `GOOGLE_CLIENT_SECRET` | backend/.env | Google OAuth client secret for YouTube |
| `CORS_ORIGINS` | backend/.env | Frontend origin (e.g., `https://douyin.toolnet.tech`) |

### AI / Metadata (REQUIRED if AI enabled)

| Variable | Source | Description |
|----------|--------|-------------|
| `AI_ENABLED` | backend/.env | `true` |
| `AI_BASE_URL` | backend/.env | `https://api.toolnet.tech/v1` |
| `AI_API_KEY` | backend/.env | ToolNet AI API key |
| `AI_MODEL` | backend/.env | `youtube-douyin` |

### YouTube Comment Reply (REQUIRED if enabled)

| Variable | Source | Description |
|----------|--------|-------------|
| `COMMENT_REPLY_ENABLED` | backend/.env | `true` |
| `COMMENT_SCAN_ENABLED` | backend/.env | `true` |
| `COMMENT_SCAN_INTERVAL_MINUTES` | backend/.env | `10` |
| `COMMENT_WORKER_STARTUP_DELAY_SECONDS` | backend/.env | `15` |
| `COMMENT_SCAN_VIDEOS_PER_CHANNEL` | backend/.env | `5` |
| `COMMENT_THREADS_MAX_PAGES` | backend/.env | `2` |
| `COMMENT_REPLY_DAILY_LIMIT` | backend/.env | `20` |
| `COMMENT_REPLY_MIN_INTERVAL_SECONDS` | backend/.env | `180` |
| `COMMENT_REPLY_MODEL` | backend/.env | `groq/qwen/qwen3.8-27b` |
| `COMMENT_REPLY_FALLBACK_MODEL` | backend/.env | `gpt-oss-20b` |
| `COMMENT_REPLY_TEMPERATURE` | backend/.env | `0.3` |
| `COMMENT_REPLY_MAX_TOKENS` | backend/.env | `80` |

### Rcuts / Douyin Downloader (REQUIRED)

| Variable | Source | Description |
|----------|--------|-------------|
| `RCUTS_API` | root/.env + backend/.env | Primary Rcuts endpoint (`http://api.rcuts.com/Video/DouYin.php`) |
| `RCUTS_PRIMARY_API` | root/.env + backend/.env | Primary All endpoint (`http://api.rcuts.com/Video/DouYin_All.php`) |
| `RCUTS_FALLBACK_API` | root/.env + backend/.env | Fallback endpoint (`http://api.rcuts.com/Video/DouYin.php`) |

### RapidAPI / Douyin Inventory (REQUIRED for auto-import)

| Variable | Source | Description |
|----------|--------|-------------|
| `RAPIDAPI_KEY` | backend/.env | RapidAPI subscription key |
| `DOUYIN_RAPIDAPI_HOST` | backend/.env | `douyin-china-tiktok-all-api.p.rapidapi.com` |
| `DOUYIN_RAPIDAPI_BASE_URL` | backend/.env | `https://douyin-china-tiktok-all-api.p.rapidapi.com` |
| `DOUYIN_RAPIDAPI_USER_POSTS_PATH` | backend/.env | `/api/douyin/get-user-video-list/v3` |
| `DOUYIN_RAPIDAPI_ENABLED` | backend/.env | `true` |
| `DOUYIN_CREATOR_PROVIDER` | backend/.env | `rapidapi_justone` |
| `RAPIDAPI_MONTHLY_REQUEST_LIMIT` | backend/.env | `20` |
| `RAPIDAPI_QUOTA_SAFETY_MARGIN` | backend/.env | `1` |
| `DOUYIN_INITIAL_IMPORT_MAX_PAGES` | backend/.env | `50` |
| `DOUYIN_INITIAL_IMPORT_PAGE_DELAY_SECONDS` | backend/.env | `0.5` |
| `DOUYIN_REFRESH_MAX_PAGES` | backend/.env | `3` |
| `DOUYIN_AUTO_SCAN_ENABLED` | backend/.env | `false` (critical: no scheduled scanning) |

### Douyin Feed API (OPTIONAL - self-hosted fallback)

| Variable | Source | Description |
|----------|--------|-------------|
| `DOUYIN_FEED_API_BASE_URL` | backend/.env | Self-hosted Evil0ctal API |
| `DOUYIN_FEED_API_KEY` | backend/.env | API key for self-hosted |
| `DOUYIN_FEED_API_ENABLED` | backend/.env | `false` (default) |
| `DOUYIN_MAX_PAGES_PER_SCAN` | backend/.env | `3` |

### Encryption / Security (REQUIRED)

| Variable | Source | Description |
|----------|--------|-------------|
| `SESSION_ENCRYPTION_KEY` | backend/.env | Fernet key for session encryption (fallback: ADMIN_TOKEN) |
| `APP_ENCRYPTION_KEY` | backend/.env | Per-source cookie encryption key |
| `DOUYIN_COOKIES_B64` | backend/.env | Base64 Netscape cookies (optional, global PlatformAccount preferred) |

### Scheduler / Worker (REQUIRED)

| Variable | Source | Description |
|----------|--------|-------------|
| `WORKER_ENABLED` | backend/.env | `true` |
| `WORKER_POLL_SECONDS` | backend/.env | `5` |
| `SCHEDULER_ENABLED` | backend/.env | `true` |
| `SCHEDULER_POLL_SECONDS` | backend/.env | `60` |
| `SCHEDULER_STARTUP_DELAY_SECONDS` | backend/.env | `10` |
| `MONITOR_ENABLED` | backend/.env | `true` (but Douyin auto-scan disabled) |
| `MONITOR_POLL_SECONDS` | backend/.env | `300` |
| `TEMP_DIR` | backend/.env | `/tmp/douyin-youtube` |

### OPTIONAL / STALE / UNUSED

| Variable | Status | Notes |
|----------|--------|-------|
| `NORTHFLANK_TOKEN` | STALE | Only for Northflank admin, not app runtime |
| `GITHUB_TOKEN` | UNUSED | Only for CI/CD, not app runtime |
| `DOUYIN_COOKIES_B64` | LEGACY | Superseded by global PlatformAccount |
| `revid_*` | UNUSED | RevidAPI disabled by default |
| `douyin_creator_fallbacks_enabled` | OFF | Fallbacks disabled |
| `youtube_comment_scan_interval_minutes` | ALIAS | Use `comment_scan_interval_minutes` |

---

## RCUTS Configuration Analysis

**From code (config.py):**
```python
rcuts_primary_api_url: str = Field(default="http://api.rcuts.com/Video/DouYin_All.php", validation_alias="RCUTS_PRIMARY_API_URL")
rcuts_fallback_api_url: str = Field(default="http://api.rcuts.com/Video/DouYin.php", validation_alias="RCUTS_FALLBACK_API_URL")
```

**Semantic from code:**
- `RCUTS_PRIMARY_API` → `DouYin_All.php` (full metadata)
- `RCUTS_FALLBACK_API` → `DouYin.php` (basic metadata)
- Code tries primary first, falls back to fallback
- Update URLs (`/update/249` and `/update/247`) are for Rcuts internal use only

**Current values (root/.env):**
- `RCUTS_PRIMARY_API=http://api.rcuts.com/Video/DouYin_All.php`
- `RCUTS_FALLBACK_API=http://api.rcuts.com/Video/DouYin.php`

---

## DATABASE_URL Analysis

**Current (backend/.env):**
```
postgresql://postgres.qrnbkiivmxsiyvqfouug:Tan0905132580@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres
```

- Uses Supabase **pooled** connection (port 5432)
- Host: `aws-0-ap-southeast-1.pooler.supabase.com`
- **NO** Northflank PostgreSQL needed
- **NO** Redis needed (app uses in-memory/DB for locking)

---

## Northflank Service Spec (for manual creation)

```yaml
# Northflank service configuration
name: douyin-youtube
project: douyin-youtube (or similar)
repo: LETAN-Media/douyin-youtube
branch: main
buildContext: /backend
dockerfilePath: /backend/Dockerfile
computePlan: nf-compute-20
instances: 1
autoScale: false
port: 8000
protocol: HTTP
public: true
healthCheckPath: /health
healthCheckInterval: 30
healthCheckTimeout: 10
```

### Docker Build Args (if needed)
- No special build args required
- Uses `backend/Dockerfile` which installs from `requirements.txt`
- Playwright Chromium installed at build time

---

## Deployment Steps (Manual - due to API auth issue)

1. **Create Northflank Personal Access Token (PAT):**
   - Go to Northflank Dashboard → Account → Personal Access Tokens
   - Create token with `projects:read`, `projects:write`, `services:read`, `services:write`, `deployments:read`, `deployments:write`, `environment-variables:read`, `environment-variables:write`
   - Save securely

2. **Create/Configure Project & Service:**
   - If project doesn't exist: Create project `douyin-youtube`
   - Create service `douyin-youtube` from GitHub repo `LETAN-Media/douyin-youtube`
   - Set build context: `/backend`, Dockerfile: `/backend/Dockerfile`
   - Compute: `nf-compute-20`, 1 instance
   - Port: 8000, HTTP public
   - Health check: `/health`

3. **Sync Environment Variables:**
   - Use Northflank Dashboard → Service → Environment Variables
   - Add all REQUIRED variables from audit above
   - Mark secrets as "Secret" type (encrypted)
   - Do NOT add `NORTHFLANK_TOKEN`, `GITHUB_TOKEN` to runtime

4. **Trigger Deployment:**
   - Push to `main` branch triggers auto-build
   - Or manually trigger from Northflank Dashboard

5. **Verify:**
   - Check build logs for success
   - Check deployment logs for FastAPI startup
   - Test `GET /health` on generated public URL
   - Verify DB connection, scheduler, comment worker, reconciler in logs

---

## Duplicate Worker Protection Strategy

**Risk:** Render production (currently running) + Northflank (new) both executing:
- Scheduler → duplicate video uploads
- Comment worker → duplicate replies
- Reconciler → race conditions

**Protection Mechanisms (code already has):**

1. **Scheduler idempotency** (`scheduler.py`):
   - `schedule_slot_key` unique constraint (`destination_id:slot_isoformat`)
   - `get_due_slots()` with catch-up but `UNIQUE` constraint prevents duplicates
   - On restart, same slots claimed → skipped via `IntegrityError` handling

2. **Publication unique constraint** (`models.py`):
   - `uq_publication_video_destination` on `(douyin_video_id, destination_id)`
   - Prevents same video published twice to same channel

3. **Job duplicate protection** (`worker.py`):
   - `claim_job()` uses `FOR UPDATE SKIP LOCKED` - only one worker claims a job
   - `schedule_slot_key` on `VideoJob` prevents duplicate job creation

4. **Reconciler safety** (`youtube_reconciler.py`):
   - Read-only `videos.list` check - never re-uploads
   - Only flips `scheduled → published` when YouTube confirms public

5. **Manual publish duplicate check** (`main.py`):
   - Checks `Publication.status == published` + `DouyinVideo.video_id` match
   - Returns 409 `DUPLICATE_VIDEO` with existing URL

**Action for Cutover:**
- **Option A (Recommended):** Scale Render worker to 0 *before* Northflank deployment goes live
  - Render Dashboard → Service → Scale to 0 instances
  - Then deploy Northflank
- **Option B:** Keep both running but accept minimal duplicate risk during overlap window
  - Scheduler slots won't duplicate due to `schedule_slot_key`
  - Comment worker uses `youtube_reply_id` check before replying
  - Reconciler is read-only

---

## Generated Northflank Public URL Pattern

Expected format: `https://douyin-youtube-<project>-<random>.nf.dev` or custom domain

Health check: `GET https://<generated-url>/health`

---

## Ready for DNS Cutover Checklist

- [ ] Northflank PAT created and tested
- [ ] Project & Service created on Northflank
- [ ] All REQUIRED ENV variables synced
- [ ] Build SUCCESS
- [ ] Deployment RUNNING
- [ ] `/health` returns 200
- [ ] DB connection OK in logs
- [ ] Scheduler started in logs
- [ ] Comment worker started in logs
- [ ] YouTube reconciler started in logs
- [ ] Render worker scaled to 0 (or cutover scheduled)
- [ ] Manual test: publish a video via Northflank API

---

## Final Report Template

```
NORTHFLANK AUTH: FAIL (team token lacks API perms; need PAT)

Project: douyin-youtube (to be created/verified)
Service: douyin-youtube (to be created/verified)
Build context: /backend
Dockerfile: /backend/Dockerfile
Port: 8000 HTTP public
Generated URL: <pending deployment>

ENV required: ~45
ENV synced: 0 (pending PAT)
Missing ENV: DATABASE_URL, ADMIN_TOKEN, PUBLIC_BASE_URL, GOOGLE_*, AI_*, RAPIDAPI_*, RCUTS_*, COMMENT_REPLY_*, etc.

Build: PENDING
Deployment: PENDING
/health: PENDING
Supabase: PASS (external, verified)
Scheduler: PENDING (code ready, duplicate-safe)
Comment worker: PENDING (code ready, duplicate-safe)
YouTube reconciler: PENDING (code ready, read-only)
Redis required: NO
Northflank PostgreSQL used: NO

Duplicate-worker protection: PASS (code-level idempotency + unique constraints)
Ready for DNS cutover: NO (deployment not yet verified)
```

**Next Steps:**
1. Generate Northflank PAT with full scopes
2. Create project/service or verify existing
3. Sync all ENV variables
4. Trigger deployment and verify
5. Scale Render to 0
6. Test manual publish via Northflank
7. Update Vercel dashboard API URL to Northflank
8. Cut DNS
```