// Server-side Facebook backend client. Never import from client components.
// Token stays on the server: browser polls the Next.js proxy route instead.

export type FacebookFlowStepState =
  | "idle"
  | "running"
  | "done"
  | "error"
  | "not_configured";

export interface FacebookFlowState {
  pipeline_id: string;
  live: boolean;
  sources: number;
  inventory: number;
  queued: number;
  processing: number;
  failed: number;
  steps: {
    source: FacebookFlowStepState;
    inventory: FacebookFlowStepState;
    ai_metadata: FacebookFlowStepState;
    scheduler: FacebookFlowStepState;
    publisher: FacebookFlowStepState;
    youtube_destination: FacebookFlowStepState;
  };
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

async function fbFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const { base, token } = requireEnv();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const res = await fetch(`${base}${path}`, {
      ...init,
      headers: { "X-Admin-Token": token, ...(init.headers ?? {}) },
      cache: "no-store",
      signal: controller.signal,
    });
    if (res.status === 401) {
      throw new FacebookApiError(401, "Facebook backend authentication failed.");
    }
    if (res.status === 404) {
      throw new FacebookApiError(404, "Không tìm thấy pipeline.");
    }
    if (!res.ok) {
      throw new FacebookApiError(res.status, "Backend Facebook gặp lỗi.");
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

export async function getFacebookPipelineDetail(pipelineId: string): Promise<FacebookPipelineDto> {
  return fbFetch<FacebookPipelineDto>(
    `/api/facebook/pipelines/${encodeURIComponent(pipelineId)}`,
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
