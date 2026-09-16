// Central server-side API client.
// Browser -> Next.js server -> FastAPI. ADMIN_TOKEN never leaves the server.

import { getServerEnv } from "./env";
import type {
  DashboardPipelineRow,
  Destination,
  DestinationStatus,
  DouyinSource,
  FlowState,
  InventoryList,
  Job,
  Pipeline,
  PipelineStats,
  Publication,
  VideoWithPublications,
  YoutubeStatus,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function friendlyMessage(status: number, detail: string): string {
  if (detail) return detail;
  switch (status) {
    case 401:
      return "Unauthorized: kiểm tra DOUYIN_ADMIN_TOKEN trên server.";
    case 404:
      return "Không tìm thấy dữ liệu yêu cầu.";
    case 409:
      return "Xung đột trạng thái: thao tác không hợp lệ lúc này.";
    case 422:
      return "Dữ liệu không hợp lệ.";
    default:
      return `Backend lỗi (HTTP ${status}).`;
  }
}

const GET_TIMEOUT_MS = 8000;
const MUTATION_TIMEOUT_MS = 15000;

function timeoutFor(init: RequestInit): number {
  const m = (init.method ?? "GET").toUpperCase();
  return m === "GET" ? GET_TIMEOUT_MS : MUTATION_TIMEOUT_MS;
}

async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
  opts: { timeoutMs?: number } = {},
): Promise<T> {
  const { apiUrl, adminToken } = getServerEnv();
  if (!apiUrl) throw new ApiError(500, "DOUYIN_API_URL chưa được cấu hình.");
  if (!adminToken)
    throw new ApiError(500, "DOUYIN_ADMIN_TOKEN chưa được cấu hình.");

  const headers: Record<string, string> = {
    "X-Admin-Token": adminToken,
    ...(init.headers as Record<string, string> | undefined),
  };
  if (init.body !== undefined && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  const timeoutMs = opts.timeoutMs ?? timeoutFor(init);
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  const t0 = Date.now();
  const method = (init.method ?? "GET").toUpperCase();

  let res: Response;
  try {
    res = await fetch(`${apiUrl}${path}`, {
      ...init,
      headers,
      cache: "no-store",
      signal: ctrl.signal,
    });
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") {
      throw new ApiError(
        504,
        `Backend timeout sau ${Math.round(timeoutMs / 1000)}s (${method} ${path}). Thử lại.`,
      );
    }
    throw new ApiError(
      500,
      `Không kết nối được backend: ${err instanceof Error ? err.message : String(err)}`,
    );
  } finally {
    clearTimeout(timer);
    if (process.env.NODE_ENV !== "production") {
      const dt = Date.now() - t0;
      console.log(`[api] ${method} ${path} ${dt}ms (timeout ${timeoutMs}ms)`);
    }
  }

  if (res.status === 204) return undefined as T;

  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text.slice(0, 500) };
    }
  }

  if (!res.ok) {
    const detail =
      typeof data === "object" && data !== null && "detail" in data
        ? String((data as { detail: unknown }).detail)
        : "";
    throw new ApiError(res.status, friendlyMessage(res.status, detail));
  }

  return data as T;
}

// ---------- Dashboard / pipelines ----------

export async function getDashboard(): Promise<DashboardPipelineRow[]> {
  const data = await apiFetch<{ pipelines: DashboardPipelineRow[] }>(
    "/api/dashboard",
  );
  return data.pipelines ?? [];
}

export async function listPipelines(): Promise<Pipeline[]> {
  return apiFetch<Pipeline[]>("/api/pipelines");
}

export async function getPipeline(id: string): Promise<Pipeline> {
  return apiFetch<Pipeline>(`/api/pipelines/${encodeURIComponent(id)}`);
}

export async function createPipeline(input: {
  name: string;
  slug: string;
  niche?: string;
  language?: string;
  default_privacy?: string;
  enabled?: boolean;
  timezone?: string;
  daily_upload_limit?: number;
  upload_slots?: string[];
}): Promise<Pipeline> {
  return apiFetch<Pipeline>("/api/pipelines", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function updatePipeline(
  id: string,
  input: Record<string, unknown>,
): Promise<Pipeline> {
  return apiFetch<Pipeline>(`/api/pipelines/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export async function deletePipeline(id: string): Promise<void> {
  await apiFetch<void>(`/api/pipelines/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export async function getPipelineStats(id: string): Promise<PipelineStats> {
  return apiFetch<PipelineStats>(
    `/api/pipelines/${encodeURIComponent(id)}/stats`,
  );
}

// ---------- Sources ----------

export async function listSources(pipelineId: string): Promise<DouyinSource[]> {
  return apiFetch<DouyinSource[]>(
    `/api/pipelines/${encodeURIComponent(pipelineId)}/sources`,
  );
}

export async function createSource(
  pipelineId: string,
  input: { name: string; profile_url: string },
): Promise<DouyinSource> {
  return apiFetch<DouyinSource>(
    `/api/pipelines/${encodeURIComponent(pipelineId)}/sources`,
    { method: "POST", body: JSON.stringify(input) },
  );
}

export async function updateSource(
  id: string,
  input: Record<string, unknown>,
): Promise<DouyinSource> {
  return apiFetch<DouyinSource>(`/api/sources/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export async function deleteSource(id: string): Promise<void> {
  await apiFetch<void>(`/api/sources/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export async function syncSource(id: string): Promise<{
  source_id: string;
  status: string;
  new: number;
  updated: number;
}> {
  return apiFetch(`/api/sources/${encodeURIComponent(id)}/sync`, {
    method: "POST",
  });
}

export async function syncPipeline(id: string): Promise<{
  new: number;
  updated: number;
}> {
  return apiFetch(`/api/pipelines/${encodeURIComponent(id)}/sync`, {
    method: "POST",
  });
}

// ---------- Inventory ----------

export async function listInventory(
  pipelineId: string,
  params: {
    source_id?: string;
    status?: string;
    search?: string;
    page?: number;
    page_size?: number;
  } = {},
): Promise<InventoryList> {
  const q = new URLSearchParams();
  if (params.source_id) q.set("source_id", params.source_id);
  if (params.status) q.set("status", params.status);
  if (params.search) q.set("search", params.search);
  q.set("page", String(params.page ?? 1));
  q.set("page_size", String(params.page_size ?? 20));
  return apiFetch<InventoryList>(
    `/api/pipelines/${encodeURIComponent(pipelineId)}/inventory?${q.toString()}`,
  );
}

export async function getInventoryVideo(
  pipelineId: string,
  videoId: string,
): Promise<VideoWithPublications> {
  return apiFetch<VideoWithPublications>(
    `/api/pipelines/${encodeURIComponent(pipelineId)}/inventory/${encodeURIComponent(videoId)}`,
  );
}

export async function publishNow(
  pipelineId: string,
  videoId: string,
  destinationId: string,
): Promise<Publication> {
  return apiFetch<Publication>(
    `/api/pipelines/${encodeURIComponent(pipelineId)}/inventory/${encodeURIComponent(videoId)}/publish`,
    {
      method: "POST",
      body: JSON.stringify({ destination_id: destinationId }),
    },
  );
}

// ---------- Destinations ----------

export async function listDestinations(
  pipelineId: string,
): Promise<Destination[]> {
  return apiFetch<Destination[]>(
    `/api/pipelines/${encodeURIComponent(pipelineId)}/destinations`,
  );
}

export async function createDestination(
  pipelineId: string,
  input: {
    platform: string;
    name: string;
    publish_strategy?: string;
    daily_upload_limit?: number;
    timezone?: string;
    upload_slots?: string[];
    metadata_language?: string;
    metadata_profile?: string;
  },
): Promise<Destination> {
  return apiFetch<Destination>(
    `/api/pipelines/${encodeURIComponent(pipelineId)}/destinations`,
    { method: "POST", body: JSON.stringify(input) },
  );
}

export async function getDestination(id: string): Promise<Destination> {
  return apiFetch<Destination>(`/api/destinations/${encodeURIComponent(id)}`);
}

export async function updateDestination(
  id: string,
  input: Record<string, unknown>,
): Promise<Destination> {
  return apiFetch<Destination>(
    `/api/destinations/${encodeURIComponent(id)}`,
    { method: "PATCH", body: JSON.stringify(input) },
  );
}

export async function deleteDestination(id: string): Promise<void> {
  await apiFetch<void>(`/api/destinations/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export async function getDestinationStatus(
  id: string,
): Promise<DestinationStatus> {
  return apiFetch<DestinationStatus>(
    `/api/destinations/${encodeURIComponent(id)}/status`,
  );
}

export interface DestinationStatusBatch {
  destination_id: string;
  connected: boolean;
  platform: string;
  name: string;
  daily_upload_limit: number;
  today_published: number;
  next_upload?: string | null;
  enabled: boolean;
}

/** Batch statuses: 1 request for all destinations (replaces N+1). */
export async function getDestinationStatuses(
  pipelineId: string,
): Promise<DestinationStatusBatch[]> {
  return apiFetch<DestinationStatusBatch[]>(
    `/api/pipelines/${encodeURIComponent(pipelineId)}/destinations/statuses`,
  );
}

export interface SchedulerStatusToday {
  destination_id: string;
  destination_name?: string | null;
  platform?: string | null;
  enabled: boolean;
  connected: boolean;
  published: number;
  released?: number | null;
  limit: number;
  next_slot?: string | null;
  last_skip_reason?: string | null;
  last_check_at?: string | null;
  last_job_created_at?: string | null;
}

export interface SchedulerStatus {
  enabled: boolean;
  pipeline_enabled?: boolean | null;
  last_cycle_at?: string | null;
  last_job_created_at?: string | null;
  next_slots: string[];
  inventory_available: number;
  connected_destinations: number;
  destinations_total?: number | null;
  today: SchedulerStatusToday[];
}

/** Scheduler observability: why auto-publish did/did not run. */
export async function getSchedulerStatus(
  pipelineId: string,
): Promise<SchedulerStatus> {
  return apiFetch<SchedulerStatus>(
    `/api/pipelines/${encodeURIComponent(pipelineId)}/scheduler-status`,
  );
}

export async function getSource(id: string): Promise<DouyinSource> {
  return apiFetch<DouyinSource>(`/api/sources/${encodeURIComponent(id)}`);
}

/** Realtime flow graph state: nodes + active routes. Poll every 2-5s. */
export async function getFlowState(pipelineId: string): Promise<FlowState> {
  return apiFetch<FlowState>(
    `/api/pipelines/${encodeURIComponent(pipelineId)}/flow-state`,
  );
}

// ---------- Publications ----------

export async function listPublications(params: {
  pipeline_id?: string;
  destination_id?: string;
  status?: string;
  limit?: number;
}): Promise<Publication[]> {
  const q = new URLSearchParams();
  if (params.pipeline_id) q.set("pipeline_id", params.pipeline_id);
  if (params.destination_id) q.set("destination_id", params.destination_id);
  if (params.status) q.set("status", params.status);
  q.set("limit", String(params.limit ?? 200));
  return apiFetch<Publication[]>(`/api/publications?${q.toString()}`);
}

export async function retryPublication(id: string): Promise<Publication> {
  return apiFetch<Publication>(
    `/api/publications/${encodeURIComponent(id)}/retry`,
    { method: "POST" },
  );
}

export async function skipPublication(id: string): Promise<Publication> {
  return apiFetch<Publication>(
    `/api/publications/${encodeURIComponent(id)}/skip`,
    { method: "POST" },
  );
}

export async function reschedulePublication(
  id: string,
  scheduledAtIso: string,
): Promise<Publication> {
  return apiFetch<Publication>(
    `/api/publications/${encodeURIComponent(id)}/reschedule`,
    {
      method: "POST",
      body: JSON.stringify({ scheduled_at: scheduledAtIso }),
    },
  );
}

// ---------- Jobs / YouTube ----------

export async function listJobs(): Promise<Job[]> {
  return apiFetch<Job[]>("/api/jobs");
}

export async function retryJob(id: string): Promise<Job> {
  return apiFetch<Job>(`/api/jobs/${encodeURIComponent(id)}/retry`, {
    method: "POST",
  });
}

export async function getYoutubeStatus(
  destinationId?: string,
): Promise<YoutubeStatus> {
  const q = destinationId
    ? `?destination_id=${encodeURIComponent(destinationId)}`
    : "";
  return apiFetch<YoutubeStatus>(`/api/youtube/status${q}`);
}

export async function getYoutubeOauthUrl(destinationId: string): Promise<{
  url: string;
  destination_id?: string | null;
}> {
  return apiFetch(
    `/api/youtube/oauth-url?destination_id=${encodeURIComponent(destinationId)}`,
    { method: "POST" },
  );
}

export async function getDouyinSession(): Promise<{
  configured: boolean;
  cookie_configured?: boolean;
  anonymous_access?: boolean | null;
  cookie_required?: boolean | null;
  last_validation?: string | null;
  valid: boolean;
  error?: string | null;
}> {
  return apiFetch("/api/system/douyin-session");
}

export async function startDouyinSession(): Promise<{
  session_id: string;
  status: string;
  qr_image_b64: string;
  expires_at?: string | null;
}> {
  return apiFetch("/api/douyin/session/start", { method: "POST" });
}

export async function getDouyinSessionFlow(id: string): Promise<{
  session_id: string;
  status: string;
  account_name?: string | null;
  error?: string | null;
  expires_at?: string | null;
  last_validated_at?: string | null;
  qr_image_b64?: string | null;
}> {
  return apiFetch(`/api/douyin/session/${encodeURIComponent(id)}/status`);
}

export async function getDouyinSessionAggregate(): Promise<{
  connected: boolean;
  valid: boolean;
  account_name?: string | null;
  last_validated_at?: string | null;
}> {
  return apiFetch("/api/douyin/session/status");
}

export async function validateDouyinSession(): Promise<{
  valid: boolean;
  account_name?: string | null;
  error?: string | null;
  last_validated_at?: string | null;
}> {
  return apiFetch("/api/douyin/session/validate", { method: "POST" });
}

export async function disconnectDouyinSession(): Promise<{ removed: number }> {
  return apiFetch("/api/douyin/session/disconnect", { method: "POST" });
}
