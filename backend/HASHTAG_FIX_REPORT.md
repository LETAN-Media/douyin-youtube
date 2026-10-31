# Douyin AI Profile / hashtag investigation — 2026-10-31

## Evidence and root cause

Pipeline `handsome-boys-universe` (`908c8358-c642-4abb-847f-7be64eac0798`), YouTube destination `ff47542c-e2c8-4941-ac89-1b46ee8e7e7b`.

The database stores preferred/fixed hashtags as one JSON list item containing a full line:

```json
["#HandsomeBoysUniverse #SixPackAbs #BoyDance #MensFitness #DanceChallenge"]
```

Adaptive/suggested hashtags are also one list item containing ten space-separated tags. The destination has null hashtag lists, metadata profile, language and prompt override, so it inherits the pipeline's profile. Pipeline language is `en`; niche is male dance/fitness entertainment. Its prompt asks for varied title angles, a short description, a YouTube subscription CTA, and 3–5 relevant hashtags. That prompt was previously ignored by the metadata generator, which only loaded destination prompt overrides or its default file.

All three failed publications and their linked jobs contain exactly this complete error (both passes):

```text
AI hashtags validation failed after retry; upload blocked. First error: Missing required fixed hashtags: ['#handsomeboysuniverse #sixpackabs #boydance #mensfitness #dancechallenge']. Retry error: Missing required fixed hashtags: ['#handsomeboysuniverse #sixpackabs #boydance #mensfitness #dancechallenge']
```

The old worker compared each extracted hashtag with the entire composite configured string. It could never match. Separately, the generator accepted five AI-selected tags without injecting fixed tags, while the worker required every fixed tag and three configured tags. These incompatible rules caused unnecessary AI retries and blocked uploads.

The stored first/retry error identifies a missing **composite string**, not proof that each of those individual tags was absent. The old validator had already passed its count, duplicate and banned-tag checks before reporting this error. Actual first/retry AI tag arrays were not persisted: publication descriptions are null and job descriptions empty. Local journal filtering found no matching publication logs; Northflank read access returned HTTP 401 for both available credentials. Therefore the raw runtime AI outputs could not be independently recovered.

Previous successful publications remain untouched, including `14f4ddcf-4132-42b1-8557-115b0517eace` (YouTube `t83MvlNSWro`, October 30) and `098398fd-f769-435d-a076-ba01b891f3e9` (YouTube `aaR3t6K41GI`, October 30).

## Implemented contract (latest user requirements)

- Fixed/Adaptive storage fields remain unchanged; UI calls them Preferred/Suggested Hashtags.
- Lists are optional reference data. No mandatory membership, three-tag quota, five-tag minimum, or fallback filler. More than five suggestions or fewer than three suggestions are valid configurations.
- Destination null inherits; an explicit empty list overrides inherited suggestions. Legacy space-separated list entries are normalized in memory, without modifying profiles.
- The AI chooses relevant suggestions or creates content-specific tags. Local code normalizes, deduplicates case-insensitively, removes malformed/banned tags and caps the result at five.
- Title must be nonempty and at most 100 characters; generated overlong titles are capped locally. Description including hashtags is limited to 5,000 characters. Source URLs/share text remain blocked. A legitimate YouTube CTA required by the existing prompt is allowed.
- Prompt selection: destination override, then pipeline prompt profile, then default prompt. Shared contract supplies language, grounded titles, varied phrasing, meaningful descriptions, optional hashtags, and no SEO stuffing.
- Generator and worker share `hashtag_policy.py`. Hashtag normalization does not trigger another AI call or replace title/prose with newly generated content.
- Existing DNA locks remain separate and mandatory. New DNA does not copy optional profile tags into locks. Invalid/banned locks or more than five unique locked tags produce an explicit conflict rather than silently dropping locks. No stored DNA was changed. This destination currently has no DNA record.
- Retry endpoints check publication external ID/URL and linked jobs' YouTube IDs first; conflicts return HTTP 409. Worker deduplication now reads the actual publication field `external_post_id`.

## Separate Dashboard HTTP 500

Production `GET /api/pipelines/908c8358-c642-4abb-847f-7be64eac0798/scheduler-status` returned **500**, body `Internal Server Error`.

An isolated regression test reproduced `NameError: name 'DouyinScanJob' is not defined` in `pipeline_scheduler_status`, which queries that model without importing it. The fix imports `DouyinScanJob`. This is independent of metadata generation or hashtag validation. Existing scheduler-status regression coverage now passes.

Production checks returned HTTP 200 for `/api/dashboard`, pipeline detail, pipeline stats, destinations, flow-state, inventory, and `/api/publications?pipeline_id=…&limit=200`. The scheduler-status production check was performed before deployment; this task does not claim a post-deployment HTTP 200.

## Three publication states and preview validation

| Publication | Started (UTC, October 31) | Linked job | Final observed state | YouTube/external ID |
| --- | --- | --- | --- | --- |
| `d67b8b1d-51a6-4d03-9e30-1199e6365eea` | 01:00:54 | `fb441e71-9f0a-42ba-ab86-7ac8a56019f5` | failed, attempts=2 | none |
| `6307e580-287d-4c19-ae8d-2fd767a59a95` | 07:00:11 | `f8ee0202-b7fc-4a4c-ad96-ca72587eb1f6` | failed, attempts=2 | none |
| `eceb89c4-7932-4101-922d-b95e5d7b0cc0` | 10:01:05 | `d78973a1-1a56-48d5-897a-074ebb822c4b` | failed, attempts=2 | none |

Read-only database queries and three AI preview generations were performed. All three previews passed the new technical metadata validator (five, five and three tags respectively). Preview JSON is local only at `/tmp/handsome-metadata-previews.json`; no metadata was written to the database.

**Content-quality limit:** stored video titles are numeric IDs and the jobs' parser titles are only `【抖音无水印】解析成功` (parser success boilerplate). The AI itself flagged the preview context as insufficient. These are structural smoke tests, not publish-ready content approvals. A future explicitly requested retry must obtain usable source context, as the worker normally attempts through its download/parser step. No YouTube upload/retry, history reset, profile edit, or successful-publication update was performed.

## Files and verification

Production code: `app/hashtag_policy.py`, `app/ai_metadata.py`, `app/worker.py`, `app/channel_dna.py`, `app/main.py`, `prompts/youtube_shorts_en.txt`.

Regression coverage: `tests/test_hashtag_policy.py`, `tests/test_channel_dna.py`, `tests/test_comment_reply.py`, `tests/test_joybeat_content_match.py`, `tests/test_tenant_isolation.py`. The tenant fixture now uses a permitted DNA tag instead of the already-banned standalone `#joybeat`; explicit banned-lock conflict coverage is separate.

Dashboard: `components/pipeline/PipelineForms.tsx`, `app/channels/[destinationId]/ChannelWorkspaceClient.tsx` (labels and explanatory text only).

Tests run against an isolated SQLite database from `/tmp` so production `.env` settings do not leak into the suite. Dashboard production build passed, including TypeScript and 49 static pages. Python compileall and git diff whitespace checks passed. Final backend suite: **395 passed, 5 skipped, 9 subtests passed** in 43.98s. Skips require connected YouTube destinations or production workspace fixtures; no tests failed.

Pre-existing edits to `.github/workflows/ci.yml`, `backend/app/douyin_self_hosted.py`, and untracked `backend_youtube/` are excluded from this change. No other platform backend is changed.
