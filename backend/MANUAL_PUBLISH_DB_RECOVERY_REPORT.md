# Vibe Men World: Manual Publish database recovery

Investigation: 2026-10-31 UTC. Scope: Douyin backend and the Channel Workspace hashtag label only. No YouTube insert/update/delete API was invoked during investigation or tests.

## Verified production evidence

- Pipeline `vibe-men-world`: `29241364-5847-4138-ae41-c2f7f44242c5`.
- Destination: `e46a50af-1649-4685-bf08-82132a11f7b3`, owned YouTube channel `UC1pYnr1C2OeiDhepR_yI0XQ` (VibeMen World).
- Manual Publication `3c3d5776-3dbd-4cd4-bb21-dab5979daa94`, Job `e0fb18f6-1faf-4919-bf0d-b23be878222f`, source `7695801167875869297` / `https://v.douyin.com/vmuC7EtIX6Q/`.
- Publication created 14:33:40.025109; processing started 14:33:42.564176; Job failure persisted 14:33:54.039927.
- Exact persisted error: `Hrana: ` + `` `http error: `connection error: Connection reset by peer (os error 104)`` ``.
- Publication and Job initially had no YouTube ID. That did **not** mean the upload failed.
- Owned-channel uploads playlist: all 40 entries inspected. Exactly one entry matched both the full title and description: `0EXAApCOo1c`, “Smart Choices Beat Hard Work Every Time”. YouTube `videos.list` confirmed matching channel, `privacyStatus=public`, `uploadStatus=processed`, `processingStatus=succeeded`, published at 14:34:11Z. Metadata contains four hashtags: `#mindset #success #growth #motivation`.
- A separate automatic Publication `85488b73-92d7-4ecf-8216-beee1c5104ad` / Job `9d3e8d81-78db-4c6b-a007-5d9f59d31aa3` failed at 16:02:28 with: `interactive transaction was rolled back because the stream was idle for too long; retry the transaction` / `SQLITE_BUSY`. The channel also contains `kh2q88u-Ips` (Public, processed, published 16:02:53Z). Its mapping to this automatic job is not established by the available stored metadata, so that Publication was not modified or retried.

## Request and failure path

Channel Workspace calls `POST /api/channels/{destination_id}/publish`, which restricts the destination then delegates to `/api/manual/publish`. The request creates a Publication and pending VideoJob; the worker downloads, prepares metadata, uploads, then persists the result. Both routes declare HTTP 202; historical access logs were unavailable, so the actual response status for this individual request is not claimed.

At investigation baseline `e5bb1b1`, `worker.process_job()` kept a `SessionLocal.begin()` transaction open across AI generation and `youtube.upload_video()`. The YouTube ID was written only in a subsequent transaction. A reset or expired Hrana transaction after the external effect therefore entered the ordinary failure handler with no durable ID. Restart recovery also requeued `uploading` jobs. Those two defects made a successful upload appear Failed and made a subsequent retry unsafe.

The database error is verified from persisted production errors, and the successful upload is verified independently through YouTube. **The exact historical failing SQL statement cannot be established**: persisted errors contain no SQL/traceback; local journal has no matching deployed worker traceback; both configured Northflank contexts returned HTTP 401. The transaction-end COMMIT after `upload_video()` and before ID persistence is a source-code-supported candidate, not a proven historical statement. New SQL diagnostics log the failing statement without bound parameters, and worker logs identify job, phase, and returned ID.

## Connection lifecycle and fix

- Existing remote QueuePool had size 5, overflow 5, checkout timeout 30 seconds, recycle 60 seconds, pre-ping enabled. Pre-ping only helps at checkout; it cannot protect an already-open transaction left idle during AI/YouTube HTTP calls.
- Remote connections explicitly disable the SQLite thread-affinity check, because QueuePool can lend a connection to different worker/request threads sequentially.
- Pool limits/recycle/checkout timeout are now configurable with `DB_POOL_SIZE`, `DB_POOL_MAX_OVERFLOW`, `DB_POOL_TIMEOUT_SECONDS`, `DB_POOL_RECYCLE_SECONDS`; remote pool uses LIFO.
- The installed `libsql_experimental.connect` exposes no HTTP request timeout parameter. Pool timeout is **not** represented as an HTTP timeout. No unsupported timeout option was added.
- Transient Hrana reset/idle errors invalidate the broken connection. Replay-safe DB units get up to three attempts, fresh sessions, exponential backoff and jitter, capped delay. Whole publish requests and YouTube uploads are never wrapped in DB retry.
- AI generation, OAuth refresh, and YouTube upload run outside database transactions.
- A deterministic remote upload intent is committed before upload. A per-Publication ownership key prevents different jobs uploading the same Publication. An ambiguous intent commit is held for reconciliation, not blindly retried externally.
- Confirmed terminal YouTube quota rejections retain the existing quota-pause policy. Only an explicit rejection releases an intent for a later permitted attempt; transport failures never do.
- After YouTube returns an ID, the worker logs it, fsyncs an atomic receipt, and retries only DB finalization. Finalization uses deterministic assignments and preserves timestamps/attempt history on replay.
- If DB finalization remains unavailable, the ID/receipt is retained and the job is held as `upload_unknown`. Worker polling and startup can finalize trusted known-ID receipts without uploading. Unknown outcomes remain held; retry and Manual Publish resubmission reject them with HTTP 409.
- Before-upload DB failures remain distinct (`BEFORE_UPLOAD`) and can be retried once connectivity returns. Failure recording/startup recovery are protected so a transient database error does not escape and terminate the worker/startup recovery path. Request-level transient DB errors return HTTP 503 with a stable code and a warning to check publication state before resubmitting.
- Mount `UPLOAD_JOURNAL_DIR` on persistent storage for receipt recovery across container replacement. Default is `/tmp/douyin-youtube-upload-receipts`. If ephemeral storage is lost during a DB outage, the remote intent still blocks reupload; manual YouTube reconciliation is required. No storage durability beyond that is claimed.

## Manual Publication reconciliation performed

Only the verified Manual Publication, its linked Job, and source-video mirror were corrected to Published with `0EXAApCOo1c`. No upload was performed. Original errors, timestamps, attempt counts, and YouTube evidence are preserved in AppSetting `publication_reconciliation:3c3d5776-3dbd-4cd4-bb21-dab5979daa94`.

All 116 previously Published Publications were compared before/after: status, title, description, external ID/URL, published time, attempt count, created time, and started time were unchanged. Attempt counts of the reconciled Publication and Job were also unchanged. No AI Profile, scheduling configuration, or other backend was changed.

Investigation artifacts (without OAuth credentials): `/tmp/vibe-db-audit/snapshot.json`, `youtube-uploads.json`, `video-status.json`, `video-file-evidence.json`, `reconciliation-before.json`, `reconciliation-result.json`.

## Metadata/UI behavior

AI Content Mismatch remains advisory for Manual Publish: the UI explicitly says publishing is allowed and the manual upload path does not enforce the scheduler's automatic content-selection gate. Tests exercise manual metadata outside database transactions without a mismatch gate. The hashtag label counts actual unique tags instead of always saying five. Existing hashtag policy, title, and description rules are unchanged.

## Verification

Regression coverage includes reset/reconnect with a new session, bounded retries/backoff, nontransient errors, pre-upload outage without upload/crash, post-upload DB outage, automatic DB-only receipt reconciliation, lost commit acknowledgements before and after upload, uncertain outcomes across restart, two overlapping jobs for one Publication, duplicate manual submission with/without a source ID, legacy ambiguous Hrana failures, safe pre-upload retries, HTTP 503, and statement diagnostics without parameter disclosure.

Final test and deployment results are recorded in the delivery response. Production health exposes `upload_recovery.version=1` and `unknown_outcome_blocks_retry=true` to verify that the new safety path is deployed without testing a real upload.
