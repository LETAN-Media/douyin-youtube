// Server-side TikTok backend client. Never import from client components.
// Mirrors lib/facebook-api.ts but targets the TikTok backend.

import type { Pipeline, PipelineStats, Publication } from "./types";

export class TikTokApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export interface TikTokPipelineDto {
  id: string;
  name: string;
  slug: string;
  enabled: boolean;
  auto_publish: boolean;
  youtube_upload_mode?: "shorts" | "video" | "both";
}

export interface TikTokSourceDto {
  id: string;
  pipeline_id: string;
  username: string;
  display_name: string | null;
  source_url: string | null;
  enabled: boolean;
  initial_scan_completed: boolean;
  crawl_complete: boolean;
  discovered_total: number;
  last_scan_at: string | null;
  last_scan_status: string | null;
  last_scan_error: string | null;
}

export interface TikTokSummaryDto {
  pipeline: TikTokPipelineDto;
  sources: number;
  inventory: number;
  destinations: number;
  published: number;
  failed: number;
  queued: number;
  processing: number;
  auto_publish: boolean;
}

export interface TikTokReelDto {
  id: string;
  source_id: string;
  reel_id: string;
  reel_url: string | null;
  caption: string | null;
  thumbnail_url: string | null;
  source_published_at: string | null;
  duration: number | null;
  play_count: number | null;
  discovered_at: string | null;
  status: string;
  retry_count: number;
  last_error: string | null;
  youtube_video_id: string | null;
}

export interface TikTokDestinationDto {
  id: string;
  pipeline_id: string;
  pipeline_name?: string | null;
  account_id: string | null;
  channel_id: string | null;
  channel_name: string | null;
  channel_avatar_url: string | null;
  visibility: string;
  enabled: boolean;
  connected: boolean;
  connected_at: string | null;
  is_default?: boolean;
}

export interface TikTokManualResolveDto {
  source_url: string;
  video_id: string;
  caption: string | null;
  thumbnail: string | null;
  duration: number | null;
  play_count: number | null;
  provider: string;
}

export interface TikTokManualPublicationDto {
  id: string;
  destination_id: string;
  pipeline_id: string;
  channel_name?: string | null;
  pipeline_name?: string | null;
  source_url: string;
  source_hash?: string;
  caption: string | null;
  thumbnail_url: string | null;
  duration: number | null;
  youtube_title: string | null;
  youtube_description: string | null;
  youtube_hashtags_json: string | null;
  visibility: string;
  publish_at: string | null;
  status: string;
  stage: string | null;
  youtube_video_id: string | null;
  error_code: string | null;
  error: string | null;
  retry_count: number;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
}

function baseUrl(): string {
  const envUrl = (process.env.TIKTOK_API_URL ?? "").trim().replace(/\/+$/, "");
  return envUrl || "https://tiktok-api.toolnet.tech";
}

function adminToken(): string {
  const envToken = (process.env.TIKTOK_ADMIN_TOKEN ?? process.env.ADMIN_TOKEN ?? "").trim();
  return envToken || "d89dc04e382cef37a864fee96faf3e2271f3b7db8eae95f28901b9865797a565";
}

function requireEnv(): { base: string; token: string } {
  const base = baseUrl();
  if (!base) throw new TikTokApiError(500, "TIKTOK_API_URL chưa được cấu hình.");
  const token = adminToken();
  if (!token) throw new TikTokApiError(500, "TIKTOK_ADMIN_TOKEN chưa được cấu hình.");
  return { base, token };
}

async function ttFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const { base, token } = requireEnv();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const res = await fetch(`${base}${path}`, {
      ...init,
      headers: {
        "Authorization": `Bearer ${token}`,
        "X-Admin-Token": token,
        ...(init.headers ?? {}),
      },
      cache: "no-store",
      signal: controller.signal,
    });
    if (res.status === 401) {
      throw new TikTokApiError(401, "TikTok backend authentication failed.");
    }
    if (res.status === 404) {
      throw new TikTokApiError(404, "Không tìm thấy resource.");
    }
    if (!res.ok) {
      const text = await res.text();
      throw new TikTokApiError(res.status, text || `HTTP ${res.status}`);
    }
    const text = await res.text();
    return JSON.parse(text || "{}") as T;
  } finally {
    clearTimeout(timer);
  }
}

export async function listTikTokPipelines(): Promise<TikTokPipelineDto[]> {
  return ttFetch<TikTokPipelineDto[]>("/api/tiktok/pipelines/");
}

export async function createTikTokPipeline(body: {
  name: string;
  slug?: string;
  auto_publish?: boolean;
  enabled?: boolean;
}): Promise<TikTokPipelineDto> {
  return ttFetch<TikTokPipelineDto>("/api/tiktok/pipelines/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function getTikTokPipeline(pipelineId: string): Promise<TikTokPipelineDto> {
  return ttFetch<TikTokPipelineDto>(`/api/tiktok/pipelines/${encodeURIComponent(pipelineId)}`);
}

export async function updateTikTokPipeline(
  pipelineId: string,
  payload: {
    enabled?: boolean;
    auto_publish?: boolean;
    name?: string;
    youtube_upload_mode?: "shorts" | "video" | "both";
  },
): Promise<TikTokPipelineDto> {
  return ttFetch<TikTokPipelineDto>(`/api/tiktok/pipelines/${encodeURIComponent(pipelineId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function toggleTikTokAutoPublish(
  pipelineId: string,
  autoPublish: boolean,
): Promise<TikTokPipelineDto> {
  return ttFetch<TikTokPipelineDto>(
    `/api/tiktok/pipelines/${encodeURIComponent(pipelineId)}/auto_publish`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ auto_publish: autoPublish }),
    },
  );
}

export async function toggleTikTokPipelineEnabled(
  pipelineId: string,
  enabled: boolean,
): Promise<TikTokPipelineDto> {
  return ttFetch<TikTokPipelineDto>(
    `/api/tiktok/pipelines/${encodeURIComponent(pipelineId)}/enable`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    },
  );
}

export async function getTikTokSummary(pipelineId: string): Promise<TikTokSummaryDto> {
  return ttFetch<TikTokSummaryDto>(`/api/tiktok/flow/pipeline/${encodeURIComponent(pipelineId)}`);
}

export async function listTikTokSources(pipelineId: string): Promise<TikTokSourceDto[]> {
  return ttFetch<TikTokSourceDto[]>(
    `/api/tiktok/sources/pipeline/${encodeURIComponent(pipelineId)}`,
  );
}

export async function createTikTokSource(body: {
  pipeline_id: string;
  username: string;
  display_name?: string;
  source_url?: string;
}): Promise<TikTokSourceDto> {
  return ttFetch<TikTokSourceDto>("/api/tiktok/sources/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function listTikTokInventory(sourceId: string): Promise<TikTokReelDto[]> {
  return ttFetch<TikTokReelDto[]>(
    `/api/tiktok/inventory/source/${encodeURIComponent(sourceId)}`,
  );
}

export async function runTikTokScan(sourceId: string): Promise<{ scan_run_id: string; status: string }> {
  return ttFetch<{ scan_run_id: string; status: string }>(
    `/api/tiktok/scan/${encodeURIComponent(sourceId)}/run`,
    { method: "POST" },
  );
}

export async function listTikTokDestinations(pipelineId: string): Promise<TikTokDestinationDto[]> {
  return ttFetch<TikTokDestinationDto[]>(
    `/api/tiktok/youtube/destinations/pipeline/${encodeURIComponent(pipelineId)}`,
  );
}

export async function createTikTokDestination(body: {
  pipeline_id: string;
  channel_id?: string;
  channel_name?: string;
  visibility?: string;
  enabled?: boolean;
}): Promise<TikTokDestinationDto> {
  return ttFetch<TikTokDestinationDto>("/api/tiktok/youtube/destinations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function startTikTokOAuth(
  pipelineId: string,
  destinationId?: string,
  return_to?: string,
): Promise<{ authorization_url: string; destination_id: string; state: string }> {
  return ttFetch<{ authorization_url: string; destination_id: string; state: string }>(
    "/api/tiktok/youtube/oauth/start",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pipeline_id: pipelineId,
        destination_id: destinationId,
        return_to,
      }),
    },
  );
}

export async function toggleTikTokDestinationEnabled(
  destinationId: string,
  enabled: boolean,
): Promise<TikTokDestinationDto> {
  return ttFetch<TikTokDestinationDto>(
    `/api/tiktok/youtube/destinations/${encodeURIComponent(destinationId)}/enable`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    },
  );
}

export async function setDefaultTikTokDestination(
  pipelineId: string,
  destinationId: string,
): Promise<TikTokDestinationDto> {
  return ttFetch<TikTokDestinationDto>(
    `/api/tiktok/youtube/destinations/${encodeURIComponent(destinationId)}/default`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pipeline_id: pipelineId }),
    },
  );
}

export async function disconnectTikTokDestination(
  destinationId: string,
): Promise<{ ok: boolean; destination_id: string; connected: boolean }> {
  return ttFetch<{ ok: boolean; destination_id: string; connected: boolean }>(
    `/api/tiktok/youtube/destinations/${encodeURIComponent(destinationId)}`,
    {
      method: "DELETE",
    },
  );
}

export async function listAllTikTokDestinations(): Promise<TikTokDestinationDto[]> {
  const pipelines = await listTikTokPipelines();
  const allDestinations: TikTokDestinationDto[] = [];
  await Promise.all(
    pipelines.map(async (pipeline) => {
      try {
        const dests = await ttFetch<TikTokDestinationDto[]>(
          `/api/tiktok/youtube/destinations/pipeline/${encodeURIComponent(pipeline.id)}`,
        );
        for (const d of dests) {
          allDestinations.push({
            ...d,
            pipeline_name: pipeline.name,
          });
        }
      } catch {
        // ignore per-pipeline errors
      }
    }),
  );
  return allDestinations;
}

export async function resolveTikTokManualVideo(url: string): Promise<TikTokManualResolveDto> {
  return ttFetch<TikTokManualResolveDto>("/api/tiktok/manual/resolve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, source_url: url }),
  });
}

export async function publishTikTokManualVideo(payload: {
  pipeline_id: string;
  destination_id: string;
  source_url: string;
  caption?: string | null;
  youtube_title?: string;
  youtube_description?: string;
  hashtags?: string[];
  visibility?: string;
  publish_at?: string | null;
}): Promise<{ publication_id: string; status: string; duplicate?: boolean }> {
  return ttFetch<{ publication_id: string; status: string; duplicate?: boolean }>(
    `/api/tiktok/manual/${encodeURIComponent(payload.pipeline_id)}/${encodeURIComponent(payload.destination_id)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export async function listTikTokManualPublications(
  pipelineId: string,
  destinationId: string,
): Promise<TikTokManualPublicationDto[]> {
  return ttFetch<TikTokManualPublicationDto[]>(
    `/api/tiktok/manual/${encodeURIComponent(pipelineId)}/${encodeURIComponent(destinationId)}`,
  );
}

export async function getTikTokManualPublication(
  pubId: string,
): Promise<TikTokManualPublicationDto> {
  return ttFetch<TikTokManualPublicationDto>(
    `/api/tiktok/manual/item/${encodeURIComponent(pubId)}`,
  );
}

export interface TikTokScheduleDto {
  id: string;
  pipeline_id: string;
  enabled: boolean;
  timezone: string;
  max_daily: number;
  batch_time: string;
  active_days?: number[];
  weekend_priority?: boolean | number;
  video_order?: "newest" | "oldest";
  min_interval_minutes?: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface TikTokQueueJobDto {
  id: string;
  pipeline_id: string;
  destination_id: string;
  reel_db_id: string;
  publication_id: string;
  status: string;
  priority: number;
  stage: string | null;
  error_code: string | null;
  error: string | null;
  scheduled_at: string | null;
  queued_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  reel_caption?: string | null;
  reel_url?: string | null;
  thumbnail_url?: string | null;
  reel_duration?: number | null;
  source_username?: string | null;
  destination_channel_name?: string | null;
  destination_channel_avatar_url?: string | null;
  youtube_upload_mode?: string | null;
  youtube_video_id?: string | null;
  retry_count?: number;
  shorts_eligible?: number | null;
  shorts_check_note?: string | null;
}

export interface TikTokSlotDto {
  id: string;
  schedule_id: string;
  slot_time: string;
  weekday?: number;
  enabled?: boolean;
  status: string;
  reel_id?: string | null;
  youtube_video_id?: string | null;
}

export async function getTikTokSchedule(pipelineId: string): Promise<TikTokScheduleDto> {
  return ttFetch<TikTokScheduleDto>(`/api/tiktok/schedule/pipeline/${encodeURIComponent(pipelineId)}`);
}

export async function updateTikTokScheduleSettings(
  pipelineId: string,
  settings: {
    timezone?: string;
    max_daily?: number;
    batch_time?: string;
    active_days?: number[];
    weekend_priority?: boolean | number;
    video_order?: "newest" | "oldest";
    min_interval_minutes?: number;
  },
): Promise<TikTokScheduleDto> {
  return ttFetch<TikTokScheduleDto>(
    `/api/tiktok/schedule/pipeline/${encodeURIComponent(pipelineId)}/settings`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings),
    },
  );
}

export async function runTikTokScheduleBatchNow(
  pipelineId: string,
  destinationId?: string,
): Promise<{
  ok: boolean;
  videos_enqueued: number;
  message: string;
  reason?: string;
  slots?: any[];
}> {
  return ttFetch(
    `/api/tiktok/schedule/pipeline/${encodeURIComponent(pipelineId)}/run-now`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ destination_id: destinationId }),
    },
  );
}

export async function listTikTokQueue(pipelineId: string): Promise<TikTokQueueJobDto[]> {
  return ttFetch<TikTokQueueJobDto[]>(
    `/api/tiktok/publish/queue/pipeline/${encodeURIComponent(pipelineId)}`,
  );
}

export async function retryTikTokQueueJob(jobId: string): Promise<{ status: string; job_id: string }> {
  return ttFetch<{ status: string; job_id: string }>(
    `/api/tiktok/publish/queue/${encodeURIComponent(jobId)}/retry`,
    { method: "POST" },
  );
}

export async function cancelTikTokQueueJob(jobId: string): Promise<{ status: string; job_id: string }> {
  return ttFetch<{ status: string; job_id: string }>(
    `/api/tiktok/publish/queue/${encodeURIComponent(jobId)}/cancel`,
    { method: "POST" },
  );
}

export async function rescheduleTikTokQueueJob(
  jobId: string,
  scheduledAt: string,
): Promise<{ status: string; job_id: string; scheduled_at: string }> {
  return ttFetch<{ status: string; job_id: string; scheduled_at: string }>(
    `/api/tiktok/publish/queue/${encodeURIComponent(jobId)}/reschedule`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scheduled_at: scheduledAt }),
    },
  );
}

export async function getTikTokScheduleSlots(pipelineId: string): Promise<TikTokSlotDto[]> {
  return ttFetch<TikTokSlotDto[]>(`/api/tiktok/schedule/pipeline/${encodeURIComponent(pipelineId)}/slots`);
}

export async function toggleTikTokScheduleEnabled(
  pipelineId: string,
  enabled: boolean,
): Promise<TikTokScheduleDto> {
  return ttFetch<TikTokScheduleDto>(
    `/api/tiktok/schedule/pipeline/${encodeURIComponent(pipelineId)}/enabled`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    },
  );
}

export async function generateTikTokScheduleSlots(
  pipelineId: string,
): Promise<{ count: number; slots: TikTokSlotDto[] }> {
  return ttFetch<{ count: number; slots: TikTokSlotDto[] }>(
    `/api/tiktok/schedule/pipeline/${encodeURIComponent(pipelineId)}/slots/generate`,
    {
      method: "PATCH",
    },
  );
}

export type TikTokFlowBackendStatus =
  | "idle"
  | "ready"
  | "waiting"
  | "running"
  | "partial"
  | "done"
  | "error"
  | "not_configured";

export interface TikTokFlowStep {
  key: string;
  title: string;
  subtitle: string;
  status: TikTokFlowBackendStatus;
  detail?: string;
}

export type TikTokFlowActiveEdge =
  | "source->inventory"
  | "inventory->ai_metadata"
  | "ai_metadata->scheduler"
  | "scheduler->publisher"
  | "publisher->youtube_destination";

export interface TikTokFlowState {
  pipeline_id: string;
  pipeline_name: string;
  live: boolean;
  auto_publish: boolean;
  sources: number;
  inventory: number;
  published: number;
  queued: number;
  processing: number;
  failed: number;
  steps: {
    source: TikTokFlowBackendStatus;
    inventory: TikTokFlowBackendStatus;
    ai_metadata: TikTokFlowBackendStatus;
    scheduler: TikTokFlowBackendStatus;
    publisher: TikTokFlowBackendStatus;
    youtube_destination: TikTokFlowBackendStatus;
  };
  details: {
    source: string;
    inventory: string;
    ai_metadata: string;
    scheduler: string;
    publisher: string;
    youtube_destination: string;
  };
  active_edges: string[];
}

export async function getTikTokFlowState(pipelineId: string): Promise<TikTokFlowState> {
  const raw: any = await ttFetch<any>(`/api/tiktok/flow/pipeline/${encodeURIComponent(pipelineId)}`);
  const pipeline = raw.pipeline || {};
  const summary = raw.summary || {};
  const sources = raw.sources || [];
  const destinations = raw.destinations || [];

  const totalSources = raw.sources_count ?? summary.total_sources ?? sources.length;
  const totalReels = raw.inventory_count ?? summary.total_reels ?? 0;
  const unpublished = summary.unpublished ?? 0;
  const published = raw.published_count ?? summary.published ?? 0;
  const queueCount = raw.queued_count ?? summary.queue_count ?? 0;

  // Use backend computed steps if present, otherwise fallback
  let steps = raw.steps;
  let details = raw.details;
  let activeEdges = raw.active_edges || [];

  if (!steps || !details) {
    let sourceStatus: TikTokFlowBackendStatus = "idle";
    let sourceDetail = "Chưa có nguồn TikTok";
    if (sources.length === 0) {
      sourceStatus = "not_configured";
    } else if (sources.some((s: any) => s.last_scan?.status === "running")) {
      sourceStatus = "running";
      sourceDetail = "Đang quét video TikTok...";
    } else if (sources.some((s: any) => s.last_scan?.status === "failed")) {
      sourceStatus = "error";
      sourceDetail = "Quét gần nhất thất bại";
    } else {
      sourceStatus = "ready";
      sourceDetail = `${sources.length} nguồn · ${totalReels} video`;
    }

    let inventoryStatus: TikTokFlowBackendStatus = "idle";
    let inventoryDetail = "Chưa có video trong kho";
    if (totalReels === 0) {
      inventoryStatus = "idle";
    } else if (unpublished > 0) {
      inventoryStatus = "ready";
      inventoryDetail = `${unpublished} video sẵn sàng`;
    } else {
      inventoryStatus = "done";
      inventoryDetail = `${published} video đã đăng`;
    }

    const aiStatus: TikTokFlowBackendStatus = unpublished > 0 ? "ready" : "idle";
    const aiDetail = unpublished > 0 ? "AI SEO sẵn sàng" : "Đang chờ video mới";

    const isAuto = Boolean(pipeline.auto_publish);
    const schedulerStatus: TikTokFlowBackendStatus = isAuto ? "ready" : "idle";
    const schedulerDetail = isAuto ? "Auto ON · Sẵn sàng đăng" : "Auto OFF (Chế độ thủ công)";

    let publisherStatus: TikTokFlowBackendStatus = "idle";
    let publisherDetail = "Chưa có lượt xuất bản";
    if (queueCount > 0) {
      publisherStatus = "waiting";
      publisherDetail = `${queueCount} video trong hàng đợi`;
    } else if (published > 0) {
      publisherStatus = "done";
      publisherDetail = `${published} video đã đăng`;
    }

    let destStatus: TikTokFlowBackendStatus = "not_configured";
    let destDetail = "Chưa liên kết kênh";
    if (destinations.length > 0) {
      const conn = destinations.find((d: any) => d.connected);
      if (conn) {
        destStatus = "ready";
        destDetail = conn.channel_name || "YouTube đã liên kết";
      } else {
        destStatus = "waiting";
        destDetail = "Chưa cấp quyền OAuth";
      }
    }

    steps = {
      source: sourceStatus,
      inventory: inventoryStatus,
      ai_metadata: aiStatus,
      scheduler: schedulerStatus,
      publisher: publisherStatus,
      youtube_destination: destStatus,
    };

    details = {
      source: sourceDetail,
      inventory: inventoryDetail,
      ai_metadata: aiDetail,
      scheduler: schedulerDetail,
      publisher: publisherDetail,
      youtube_destination: destDetail,
    };

    activeEdges = [];
    if (sourceStatus === "running") activeEdges.push("source->inventory");
    if (unpublished > 0) activeEdges.push("inventory->ai_metadata");
    if (queueCount > 0) activeEdges.push("scheduler->publisher");
  }

  return {
    pipeline_id: pipeline.id || pipelineId,
    pipeline_name: pipeline.name || "TikTok Pipeline",
    live: Boolean(pipeline.enabled ?? true),
    auto_publish: Boolean(pipeline.auto_publish),
    sources: totalSources,
    inventory: totalReels,
    published,
    queued: queueCount,
    processing: 0,
    failed: 0,
    steps,
    details,
    active_edges: activeEdges,
  };
}


export async function getProviderHealth() {
  return ttFetch<{ provider: string; healthy: boolean; available: string[] }>(
    "/health/providers",
  );
}

export interface TikTokAiSettingsDto {
  pipeline_id: string;
  enabled: boolean;
  provider: string;
  model: string;
  system_prompt: string;
  title_prompt: string;
  description_prompt: string;
  hashtag_prompt: string;
  title_template: string;
  description_template: string;
  locked_hashtags: string[];
  language: string;
  max_hashtags: number;
  include_emojis: boolean;
  tone: string;
  required_keywords: string;
  forbidden_keywords: string;
  updated_at?: string;
}

export interface TikTokAiModelOption {
  id: string;
  label: string;
  provider: string;
  is_default?: boolean;
}

export async function getTikTokAiSettings(pipelineId: string): Promise<TikTokAiSettingsDto> {
  return ttFetch<TikTokAiSettingsDto>(`/api/tiktok/ai/settings/pipeline/${encodeURIComponent(pipelineId)}`);
}

export async function updateTikTokAiSettings(
  pipelineId: string,
  settings: Partial<TikTokAiSettingsDto>,
): Promise<TikTokAiSettingsDto> {
  return ttFetch<TikTokAiSettingsDto>(`/api/tiktok/ai/settings/pipeline/${encodeURIComponent(pipelineId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
}

export async function listTikTokAiModels(): Promise<{ models: TikTokAiModelOption[] }> {
  return ttFetch<{ models: TikTokAiModelOption[] }>("/api/tiktok/ai/models");
}

export async function testTikTokAiSettings(body: {
  pipeline_id: string;
  sample_caption?: string;
  settings?: Partial<TikTokAiSettingsDto>;
}): Promise<{
  title: string;
  description: string;
  hashtags: string[];
  model: string;
  provider: string;
}> {
  return ttFetch("/api/tiktok/ai/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
