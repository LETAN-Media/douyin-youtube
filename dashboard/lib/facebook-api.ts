// Server-side Facebook backend client. Never import from client components.
// Token stays on the server: browser polls the Next.js proxy route instead.

export type FacebookFlowBackendStatus =
  | "idle"
  | "ready"
  | "waiting"
  | "running"
  | "partial"
  | "done"
  | "error"
  | "not_configured";

export type FacebookFlowActiveEdge =
  | "source->inventory"
  | "inventory->ai_metadata"
  | "ai_metadata->scheduler"
  | "scheduler->publisher"
  | "publisher->youtube_destination";

export interface FacebookFlowState {
  pipeline_id: string;
  live: boolean;
  sources: number;
  inventory: number;
  queued: number;
  processing: number;
  failed: number;
  steps: {
    source: FacebookFlowBackendStatus;
    inventory: FacebookFlowBackendStatus;
    ai_metadata: FacebookFlowBackendStatus;
    scheduler: FacebookFlowBackendStatus;
    publisher: FacebookFlowBackendStatus;
    youtube_destination: FacebookFlowBackendStatus;
  };
  details?: {
    source: string;
    inventory: string;
    ai_metadata: string;
    scheduler: string;
    publisher: string;
    youtube_destination: string;
  };
  active_stage?: string | null;
  active_edges?: FacebookFlowActiveEdge[];
}

export class FacebookApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// ---------- Real backend DTOs (mirror backend_facebook responses) ----------

export interface FacebookPipelineDto {
  id: string;
  name: string;
  slug: string;
  enabled: boolean;
  auto_publish: boolean;
}

export interface FacebookSummaryDto {
  pipeline: FacebookPipelineDto;
  sources: number;
  inventory: number;
  destinations: number;
  published: number;
  failed: number;
  queued: number;
  processing: number;
}

export interface FacebookSourceDto {
  id: string;
  pipeline_id: string;
  page_id: string;
  page_name: string | null;
  reels_url: string | null;
  enabled: boolean;
  initial_scan_completed: boolean;
  crawl_complete: boolean;
  discovered_total: number;
  last_scan_at: string | null;
  last_scan_status: string | null;
  last_scan_error: string | null;
}

export interface FacebookInventoryDto {
  id: string;
  source_id: string;
  reel_id: string;
  reel_url: string | null;
  caption: string | null;
  thumbnail_url: string | null;
  source_published_at: string | null;
  discovered_at: string | null;
  status: string;
  retry_count: number;
  last_error: string | null;
  youtube_video_id: string | null;
  youtube_published_at: string | null;
}

export interface FacebookDestinationDto {
  id: string;
  pipeline_id: string;
  channel_id: string | null;
  channel_name: string | null;
  visibility: string;
  enabled: boolean;
  connected: boolean;
}

export interface FacebookPublicationDto {
  id: string;
  reel_db_id: string;
  destination_id: string;
  status: string;
  youtube_video_id: string | null;
  started_at: string | null;
  published_at: string | null;
  last_error: string | null;
  retry_count: number;
  reel_id: string;
  channel_name: string | null;
}

function baseUrl(): string {
  return (process.env.FACEBOOK_API_URL ?? "").trim().replace(/\/+$/, "");
}

function adminToken(): string {
  return (process.env.FACEBOOK_ADMIN_TOKEN ?? "").trim();
}

function requireEnv(): { base: string; token: string } {
  const base = baseUrl();
  if (!base) throw new FacebookApiError(500, "FACEBOOK_API_URL chưa được cấu hình.");
  const token = adminToken();
  if (!token) throw new FacebookApiError(500, "FACEBOOK_ADMIN_TOKEN chưa được cấu hình.");
  return { base, token };
}

async function fbFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const { base, token } = requireEnv();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const res = await fetch(`${base}${path}`, {
      ...init,
      headers: {
        "X-Admin-Token": token,
        ...(init.headers ?? {}),
      },
      cache: "no-store",
      signal: controller.signal,
    });
    if (res.status === 401) {
      throw new FacebookApiError(401, "Facebook backend authentication failed.");
    }
    if (res.status === 404) {
      throw new FacebookApiError(404, "Không tìm thấy resource.");
    }
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      let detail: unknown = text;
      try {
        detail = JSON.parse(text);
      } catch {
        // keep raw text
      }
      throw new FacebookApiError(
        res.status,
        typeof detail === "string" ? detail : (detail as Record<string, unknown>)?.error as string || "Backend Facebook gặp lỗi.",
      );
    }
    return (await res.json()) as T;
  } catch (err) {
    if (err instanceof FacebookApiError) throw err;
    throw new FacebookApiError(503, "Không kết nối được backend Facebook.");
  } finally {
    clearTimeout(timer);
  }
}

export async function getFacebookFlowState(pipelineId: string): Promise<FacebookFlowState> {
  return fbFetch<FacebookFlowState>(
    `/api/facebook/pipelines/${encodeURIComponent(pipelineId)}/flow-state`,
  );
}

export async function listFacebookPipelines(): Promise<FacebookPipelineDto[]> {
  return fbFetch<FacebookPipelineDto[]>(`/api/facebook/pipelines`);
}

export interface CreateFacebookPipelineDto {
  name: string;
  slug: string | null;
  enabled: boolean;
  auto_publish: boolean;
}

export async function createFacebookPipeline(payload: CreateFacebookPipelineDto): Promise<FacebookPipelineDto> {
  return fbFetch<FacebookPipelineDto>(
    `/api/facebook/pipelines`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export async function getFacebookPipelineDetail(pipelineId: string): Promise<FacebookPipelineDto> {
  return fbFetch<FacebookPipelineDto>(
    `/api/facebook/pipelines/${encodeURIComponent(pipelineId)}`,
  );
}

export interface UpdateFacebookPipelineDto {
  enabled?: boolean;
  auto_publish?: boolean;
  name?: string;
}

export async function updateFacebookPipeline(
  pipelineId: string,
  payload: UpdateFacebookPipelineDto,
): Promise<FacebookPipelineDto> {
  return fbFetch<FacebookPipelineDto>(
    `/api/facebook/pipelines/${encodeURIComponent(pipelineId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export async function getFacebookSummary(pipelineId: string): Promise<FacebookSummaryDto> {
  return fbFetch<FacebookSummaryDto>(
    `/api/facebook/pipelines/${encodeURIComponent(pipelineId)}/summary`,
  );
}

export async function listFacebookSources(pipelineId: string): Promise<FacebookSourceDto[]> {
  return fbFetch<FacebookSourceDto[]>(
    `/api/facebook/pipelines/${encodeURIComponent(pipelineId)}/sources`,
  );
}

export async function listFacebookInventory(
  pipelineId: string,
  opts: { limit?: number; offset?: number; status?: string } = {},
): Promise<{ items: FacebookInventoryDto[]; total: number; unpublished: number; published: number; next_cursor: string | null }> {
  const q = new URLSearchParams();
  q.set("limit", String(opts.limit ?? 50));
  q.set("offset", String(opts.offset ?? 0));
  if (opts.status) q.set("status", opts.status);
  return fbFetch(
    `/api/facebook/pipelines/${encodeURIComponent(pipelineId)}/inventory?${q.toString()}`,
  );
}

export async function listFacebookDestinations(
  pipelineId: string,
): Promise<FacebookDestinationDto[]> {
  return fbFetch<FacebookDestinationDto[]>(
    `/api/facebook/pipelines/${encodeURIComponent(pipelineId)}/youtube-destinations`,
  );
}

export interface CreateFacebookYoutubeDestinationDto {
  visibility?: string;
  enabled?: boolean;
}

export async function createFacebookYoutubeDestination(
  pipelineId: string,
  payload: CreateFacebookYoutubeDestinationDto,
): Promise<FacebookDestinationDto> {
  return fbFetch<FacebookDestinationDto>(
    `/api/facebook/pipelines/${encodeURIComponent(pipelineId)}/youtube-destinations`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        visibility: payload.visibility ?? "public",
        enabled: payload.enabled ?? true,
      }),
    },
  );
}

export async function listFacebookPublications(
  pipelineId: string,
  opts: { limit?: number; offset?: number } = {},
): Promise<{ items: FacebookPublicationDto[]; total: number }> {
  const q = new URLSearchParams();
  q.set("limit", String(opts.limit ?? 100));
  q.set("offset", String(opts.offset ?? 0));
  return fbFetch(
    `/api/facebook/pipelines/${encodeURIComponent(pipelineId)}/publications?${q.toString()}`,
  );
}

export async function startFacebookOAuth(destinationId: string): Promise<{ authorization_url: string }> {
  return fbFetch<{ authorization_url: string }>(
    `/api/facebook/youtube-destinations/${encodeURIComponent(destinationId)}/oauth/start`,
    { method: "POST" },
  );
}

export async function triggerFacebookScan(sourceId: string): Promise<{ scan_run_id: string; status: string }> {
  return fbFetch(
    `/api/facebook/sources/${encodeURIComponent(sourceId)}/scan`,
    { method: "POST" },
  );
}

export interface FacebookAiStatsDto {
  generated: number;
  failed: number;
  pending: number;
  total_reels: number;
}

export interface FacebookAiMetadataDto {
  reel_db_id: string;
  status: string;
  metadata: { title: string | null; description: string | null; hashtags: string[] };
  model: string | null;
  generated_at?: string | null;
}

export interface FacebookAiSettingsDto {
  pipeline_id: string;
  enabled: boolean;
  system_prompt: string;
  title_template: string;
  description_template: string;
  locked_hashtags: string[];
  language: string;
  config_hash?: string;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface FacebookScheduleStatus {
  date: string;
  weekday: number;
  timezone: string;
  batch_time: string;
  batch_status: string;
  scheduled_today: number;
  daily_limit: number;
  next_batch_at: string | null;
  inventory_total?: number;
  ai_generated?: number;
  ai_pending?: number;
  ai_failed?: number;
  ai_ready?: number;
  queue_queued?: number;
  queue_processing?: number;
  queue_scheduled?: number;
  queue_failed?: number;
  queue_total?: number;
  batch_planned?: number;
  batch_uploaded?: number;
  batch_failed?: number;
  batch_last_error?: string | null;
  slots: Array<{
    weekday: number;
    time: string;
    enabled: boolean;
  }>;
  scheduler_enabled: boolean;
}

export async function getFacebookAiStats(pipelineId: string): Promise<FacebookAiStatsDto> {
  return fbFetch<FacebookAiStatsDto>(
    `/api/facebook/pipelines/${encodeURIComponent(pipelineId)}/ai-metadata/stats`,
  );
}

export async function getFacebookAiSettings(pipelineId: string): Promise<FacebookAiSettingsDto> {
  return fbFetch<FacebookAiSettingsDto>(
    `/api/facebook/pipelines/${encodeURIComponent(pipelineId)}/ai-settings`,
  );
}

export async function updateFacebookAiSettings(
  pipelineId: string,
  payload: Partial<FacebookAiSettingsDto>,
): Promise<FacebookAiSettingsDto> {
  return fbFetch<FacebookAiSettingsDto>(
    `/api/facebook/pipelines/${encodeURIComponent(pipelineId)}/ai-settings`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export async function getFacebookAiSample(
  pipelineId: string,
): Promise<FacebookAiMetadataDto | null> {
  try {
    const res = await fbFetch<{ ok: boolean; sample: FacebookAiMetadataDto | null }>(
      `/api/facebook/pipelines/${encodeURIComponent(pipelineId)}/ai-metadata/sample`,
    );
    return res?.sample ?? null;
  } catch (err) {
    if (err instanceof FacebookApiError && err.status === 404) return null;
    throw err;
  }
}

export async function getFacebookReelAiMetadata(
  reelDbId: string,
): Promise<FacebookAiMetadataDto | null> {
  try {
    return await fbFetch<FacebookAiMetadataDto>(
      `/api/facebook/reels/${encodeURIComponent(reelDbId)}/ai-metadata`,
    );
  } catch (err) {
    if (err instanceof FacebookApiError && err.status === 404) return null;
    throw err;
  }
}

export async function getFacebookScheduleStatus(pipelineId: string): Promise<FacebookScheduleStatus> {
  return fbFetch<FacebookScheduleStatus>(
    `/api/facebook/pipelines/${encodeURIComponent(pipelineId)}/schedule/status`,
  );
}

export interface FacebookScheduleDto {
  id: string;
  pipeline_id: string;
  timezone: string;
  enabled: boolean;
  max_daily_publish: number;
  batch_time: string;
  slots: Record<string, string[]>;
  created_at: string | null;
  updated_at: string | null;
}

export async function getFacebookSchedule(pipelineId: string): Promise<FacebookScheduleDto> {
  return fbFetch<FacebookScheduleDto>(
    `/api/facebook/pipelines/${encodeURIComponent(pipelineId)}/schedule`,
  );
}

export interface UpdateFacebookScheduleDto {
  enabled?: boolean;
  timezone?: string;
  max_daily_publish?: number;
  batch_time?: string;
  slots?: Record<string, string[]>;
}

export async function updateFacebookSchedule(
  pipelineId: string,
  payload: UpdateFacebookScheduleDto,
): Promise<FacebookScheduleDto> {
  return fbFetch<FacebookScheduleDto>(
    `/api/facebook/pipelines/${encodeURIComponent(pipelineId)}/schedule`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export async function runSchedulerTick(): Promise<{ checked: number; batches_started: number; videos_scheduled: number; failed: number }> {
  return fbFetch(
    `/api/facebook/scheduler/tick`,
    { method: "POST" },
  );
}

export async function runSchedulerReconcile(): Promise<{ checked: number; published: number; left_scheduled: number; errors: number }> {
  return fbFetch(
    `/api/facebook/scheduler/reconcile`,
    { method: "POST" },
  );
}

export async function scheduleToday(pipelineId: string, destinationId: string): Promise<{
  ok: boolean;
  batch_id: string | null;
  status: string;
  videos_enqueued: number;
  slots: { slot: string; publish_at: string }[];
  reason: string | null;
  message: string;
}> {
  return fbFetch(
    `/api/facebook/pipelines/${encodeURIComponent(pipelineId)}/youtube-destinations/${encodeURIComponent(destinationId)}/schedule-today`,
    { method: "POST" },
  );
}

export interface FacebookSkipResult {
  ok: boolean;
  reel_id: string;
  status: string;
}

export interface FacebookRestoreResult {
  ok: boolean;
  reel_id: string;
  status: string;
}

export interface FacebookBulkSkipResult {
  ok: boolean;
  skipped: number;
  unchanged: number;
  rejected: string[];
}

export async function skipFacebookReel(reelDbId: string): Promise<FacebookSkipResult> {
  return fbFetch<FacebookSkipResult>(
    `/api/facebook/reels/${encodeURIComponent(reelDbId)}/skip`,
    { method: "POST" },
  );
}

export async function restoreFacebookReel(reelDbId: string): Promise<FacebookRestoreResult> {
  return fbFetch<FacebookRestoreResult>(
    `/api/facebook/reels/${encodeURIComponent(reelDbId)}/restore`,
    { method: "POST" },
  );
}

export async function bulkSkipFacebookReels(
  pipelineId: string,
  reelDbIds: string[],
): Promise<FacebookBulkSkipResult> {
  return fbFetch<FacebookBulkSkipResult>(
    `/api/facebook/pipelines/${encodeURIComponent(pipelineId)}/inventory/skip`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reel_ids: reelDbIds }),
    },
  );
}
