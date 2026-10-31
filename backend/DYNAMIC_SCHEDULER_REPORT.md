# Dynamic Daily Upload Limit and Upload Slots

The scheduler now uses the effective Pipeline/Destination schedule instead of a global four-video ceiling. The same limit is checked by Settings validation, slot allocation, automatic scheduling, manual admission, promotion and the worker immediately before upload.

## Configuration and inheritance

- Pipeline Settings supplies the default daily limit, publishing window, timezone, auto/manual slots, backlog/new counts, fallback policy and minimum interval.
- A Destination only uses its own schedule when `schedule_override_enabled=true`. Channel schedule saves no longer copy those values back to the Pipeline.
- Responses include `effective_schedule`, its `source`, effective limit, hours and warnings. Pipeline/Channel Settings and Destination editors display the saved effective schedule separately from the draft preview.
- New Destinations inherit. Migration 019 keeps independently configured legacy Destination schedules as explicit overrides; exact copies follow the Pipeline. To make an existing custom Destination follow Pipeline defaults, deliberately turn off its override.
- Existing manual hours remain manual. Their publishing windows are derived from their actual earliest/latest hours. Auto distribution is enabled deliberately for existing manual schedules; changing the count with Auto OFF does not overwrite hours.
- Inputs require a positive integer. Safety ceiling is configurable with `SCHEDULER_MAX_DAILY_UPLOADS` (default 1440, the minute-resolution daily capacity). `SCHEDULER_MIN_SLOT_INTERVAL_MINUTES` defaults to 1. Publishing-window geometry can impose a lower feasible count and returns an explicit error, never a silent clamp.
- `SCHEDULER_DAILY_UPLOAD_WARNING_THRESHOLD` defaults to 20. High counts show a warning; they are not silently reduced to 4 or 6.

## Slot contract

Auto mode distributes the requested number of slots evenly, includes both window endpoints for counts greater than one, rounds to minute resolution, and rejects collisions/impossible spacing. One video uses the start time. Overnight schedules require an explicit flag and End before Start. Manual Save requires exactly the requested number of unique, in-window, adequately spaced slots.

Daily Limit 10, 08:00–23:00:

```text
08:00, 09:40, 11:20, 13:00, 14:40,
16:20, 18:00, 19:40, 21:20, 23:00
```

Preview is computed locally and does not write the database. Save validates the merged configuration and atomically stores the limit and hours. A read-only authenticated `POST /api/scheduler/preview` uses the backend contract; `GET /api/scheduler/policy` exposes deployment policy settings without credentials.

## Scheduler and protection

- Removed `SHORTS_MAX_SLOTS_PER_DAY` and the `min(global_cap, destination_limit)` clamp. `shorts_daily_limit()` and `shorts_slots_for_day()` resolve the same effective settings as the API.
- Slot priority uses the index in the effective ordered hours, in the effective timezone. A 7/3 schedule requests backlog for the first seven positions and new videos for the remaining three. Fallback to the other pool is optional. Per-source limits remain respected and are reported as `SOURCE_DAILY_LIMIT_REACHED` rather than disguised as a four-slot cap.
- Published plus reserved slots are counted using the Destination's effective local calendar day. Worker admission also counts in-flight uploads, serializes uploads to a Destination and checks the live policy again before upload. A blocked channel does not hide all other channels behind its pending queue.
- Slot keys and the existing unique reservation index prevent duplicate jobs/times. Failed/skipped Publication history is no longer deleted by automatic scheduling.
- A schedule cutover skips past newly introduced slots. Catch-up is limited to the newest due automatic slot; promotion releases at most one current reserved slot per cycle. Missed queued reservations remain unchanged for review, instead of generating a catch-up batch. Merely saving identical settings does not reset the cutover.
- Existing Publication/job times are not rewritten. A lower limit that conflicts with existing published/reserved counts returns HTTP 409 and explains the conflict.
- The old “Publish anyway” allowance cannot bypass the saved daily limit. New legacy allowance requests return HTTP 422 and direct the user to Settings; existing allowance audit rows remain readable. Manual and auto paths therefore share the same hard configured limit. The Dashboard action now opens Settings or queues into a free future slot.
- Optional `YOUTUBE_PROJECT_DAILY_UPLOAD_BUDGET` is a conservative shared project upload budget (0 means not configured). A known insufficient configured budget is rejected/explained. Remaining Google API quota is **not** claimed to be discoverable from the available API credentials.
- Provider `quotaExceeded`/`dailyLimitExceeded` errors durably pause project uploads until the next Pacific midnight. `uploadLimitExceeded` pauses only that Destination. Jobs remain pending with the reason visible; restarts do not remove the pause. This upload-count budget is not an estimate of all API units used by other API consumers.

## Verification

No real YouTube upload was made for this task. All automated tests and browser checks used isolated SQLite fixtures, dummy OAuth values, and disabled workers/scheduler/monitor/comment processing.

- Backend suite: **452 passed, 5 skipped, 9 subtests passed**. Skips require connected YouTube destinations or production workspace fixtures. Existing deprecation warnings remain.
- Scheduler regression module: 57 passing cases, including counts 1/3/5/6/10/15/20 in UTC and Asia/Ho_Chi_Minh, overnight scheduling, destination override, manual hours, migration idempotency, daily limit across restart, quota pause, source-pool fallback, settings cutover and preserving reservations.
- Frontend schedule contracts: **12 passed** with `node --experimental-strip-types tests/schedule.test.mjs`.
- `npm run lint`: TypeScript and ESLint PASS.
- `npm run build`: Next.js production build PASS, including TypeScript and static generation.
- Python compileall and `git diff --check`: PASS.

Browser acceptance used the actual production build against a local API and SQLite database. Evidence:

1. Initial saved daily limit was 3.
2. Typing 10 immediately showed the ten hours above.
3. A direct API read still returned 3 before Save.
4. In manual mode, an edited 09:41 slot survived a count change; no implicit overwrite occurred.
5. Save persisted limit 10 and exactly ten hours.
6. Destination and Channel API responses both reported effective limit 10 and those same hours. No browser console errors occurred.

The actual Scheduler functions were then run against **that browser-saved database**, with the upload worker disabled:

```json
{
  "effective_daily_limit": 10,
  "effective_slots": ["08:00", "09:40", "11:20", "13:00", "14:40", "16:20", "18:00", "19:40", "21:20", "23:00"],
  "publication_count": 10,
  "job_count": 10,
  "unique_slot_keys": 10,
  "usage": [0, 10],
  "backlog": 7,
  "new": 3,
  "worker_enabled": false,
  "youtube_uploads": 0
}
```

Local evidence is in `/tmp/dynamic-browser-proof.json`, `/tmp/dynamic-scheduler-saved-proof.json`, `/tmp/dynamic-browser-before-save.png` and `/tmp/dynamic-browser-after-save.png`. Production verification after push uses only policy/preview/status reads, never a live scheduler run or upload test.

## Changed files

Backend production: `app/schedule_policy.py`, `app/upload_quota.py`, `app/scheduler.py`, `app/worker.py`, `app/main.py`, `app/models.py`, `app/schemas.py`, `app/config.py`, `app/migrate.py`, `.env.example`.

Backend tests: `tests/test_dynamic_schedule.py`, `tests/test_inventory_scheduler.py`, `tests/test_shorts_daily_limit.py`, `tests/test_flow_state_regression.py`.

Dashboard: `components/pipeline/ScheduleFields.tsx`, `PipelineForms.tsx`, `DestinationDetail.tsx`, `DestinationsPanel.tsx`; `app/channels/[destinationId]/ChannelWorkspaceClient.tsx`; `app/pipelines/new/page.tsx`; `lib/schedule.ts`, `actions.ts`, `api.ts`, `types.ts`; `tests/schedule.test.mjs`.

Pre-existing edits to `.github/workflows/ci.yml`, `backend/app/douyin_self_hosted.py` and untracked `backend_youtube/` are excluded. No other platform backend is changed. Commit and deployment evidence are supplied in the final report.
