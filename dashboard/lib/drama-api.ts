// Server-side Drama backend client. Never import from client components.
// Token stays on the server: browser polls the Next.js proxy route instead.

export class DramaApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// ---------- Real backend DTOs (mirror backend_drama responses) ----------

export interface DramaPipelineDto {
  id: string;
  name: string;
  slug: string;
  enabled: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface DramaSummaryDto {
  pipeline: DramaPipelineDto;
  sources: number;
  inventory: number;
  series: number;
}

export interface DramaSourceDto {
  id: string;
  pipeline_id: string;
  provider: string;
  source_url: string | null;
  external_series_id: string | null;
  name: string | null;
  enabled: boolean;
  last_scan_at: string | null;
  last_scan_status: string | null;
  last_scan_error: string | null;
}

export interface DramaStoredSeriesDto {
  id: string;
  source_id: string;
  external_series_id: string;
  title: string | null;
  description: string | null;
  thumbnail_url: string | null;
  total_episodes: number | null;
  created_at: string | null;
  updated_at: string | null;
}

// Stored series alias for compatibility
export type DramaSeriesDto = DramaStoredSeriesDto;

export interface DramaDiscoverySeriesDto {
  provider: string;
  external_series_id: string;
  title: string | null;
  description: string | null;
  thumbnail_url: string | null;
  total_episodes: number | null;
}

export interface DramaProviderErrorDto {
  provider: string;
  status: "temporarily_unavailable" | "rate_limited" | "not_supported" | "upstream_error" | string;
  code?: string;
  message: string;
  retryable?: boolean;
}

export interface DramaProviderStatusDto {
  status: "ok" | "temporarily_unavailable" | "rate_limited" | "not_supported" | "upstream_error" | "unsupported" | string;
  count?: number;
  reason?: string;
  code?: string;
  message?: string;
  retryable?: boolean;
  upstream?: string;
}

export interface DramaDiscoveryResponseDto {
  items: DramaDiscoverySeriesDto[];
  providers: Record<string, DramaProviderStatusDto>;
  errors: DramaProviderErrorDto[];
  source?: "live" | "cache" | "mixed" | string;
  stale?: boolean;
  refreshing?: boolean;
  fetched_at?: string;
}

export interface DramaEpisodeDto {
  id: string;
  series_id: string;
  external_episode_id: string | null;
  episode_number: number;
  title: string | null;
  source_url: string | null;
  thumbnail_url: string | null;
  duration: number | null;
  status: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface DramaPipelineInventoryDto {
  items: DramaEpisodeDto[];
  total: number;
}

export interface DramaScanResult {
  source_id: string;
  series_found: number;
  episodes_found: number;
  series: Array<{
    external_series_id: string;
    title: string | null;
    total_episodes: number | null;
    episodes: Array<{
      external_episode_id: string | null;
      episode_number: number;
      title: string | null;
      source_url: string | null;
      thumbnail_url: string | null;
      duration: number | null;
    }>;
  }>;
}

function baseUrl(): string {
  return (process.env.DRAMA_API_URL ?? "").trim().replace(/\/+$/, "");
}

function adminToken(): string {
  return (process.env.DRAMA_ADMIN_TOKEN ?? "").trim();
}

function requireEnv(): { base: string; token: string } {
  const base = baseUrl();
  if (!base) throw new DramaApiError(500, "DRAMA_API_URL chưa được cấu hình.");
  const token = adminToken();
  if (!token) throw new DramaApiError(500, "DRAMA_ADMIN_TOKEN chưa được cấu hình.");
  return { base, token };
}

async function dramaFetch<T>(
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
      throw new DramaApiError(401, "Drama backend authentication failed.");
    }
    if (res.status === 404) {
      throw new DramaApiError(404, "Không tìm thấy resource.");
    }
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      let detail: unknown = text;
      try {
        detail = JSON.parse(text);
      } catch {
        // keep raw text
      }
      throw new DramaApiError(
        res.status,
        typeof detail === "string" ? detail : (detail as Record<string, unknown>)?.error as string || "Backend Drama gặp lỗi.",
      );
    }
    return (await res.json()) as T;
  } catch (err) {
    if (err instanceof DramaApiError) throw err;
    throw new DramaApiError(503, "Không kết nối được backend Drama.");
  } finally {
    clearTimeout(timer);
  }
}

export async function listDramaPipelines(): Promise<DramaPipelineDto[]> {
  return dramaFetch<DramaPipelineDto[]>(`/api/drama/pipelines`);
}

export interface CreateDramaPipelineDto {
  name: string;
  slug: string | null;
  enabled: boolean;
}

export async function createDramaPipeline(payload: CreateDramaPipelineDto): Promise<DramaPipelineDto> {
  return dramaFetch<DramaPipelineDto>(
    `/api/drama/pipelines`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export async function getDramaPipelineDetail(pipelineId: string): Promise<DramaPipelineDto> {
  return dramaFetch<DramaPipelineDto>(
    `/api/drama/pipelines/${encodeURIComponent(pipelineId)}`,
  );
}

export interface UpdateDramaPipelineDto {
  enabled?: boolean;
  name?: string;
}

export async function updateDramaPipeline(
  pipelineId: string,
  payload: UpdateDramaPipelineDto,
): Promise<DramaPipelineDto> {
  return dramaFetch<DramaPipelineDto>(
    `/api/drama/pipelines/${encodeURIComponent(pipelineId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export async function getDramaSummary(pipelineId: string): Promise<DramaSummaryDto> {
  return dramaFetch<DramaSummaryDto>(
    `/api/drama/pipelines/${encodeURIComponent(pipelineId)}/summary`,
  );
}

export async function listDramaSources(pipelineId: string): Promise<DramaSourceDto[]> {
  return dramaFetch<DramaSourceDto[]>(
    `/api/drama/pipelines/${encodeURIComponent(pipelineId)}/sources`,
  );
}

export interface CreateDramaSourceDto {
  provider: string;
  source_url: string | null;
  external_series_id: string | null;
  name: string | null;
  enabled: boolean;
}

export async function createDramaSource(
  pipelineId: string,
  payload: CreateDramaSourceDto,
): Promise<DramaSourceDto> {
  return dramaFetch<DramaSourceDto>(
    `/api/drama/pipelines/${encodeURIComponent(pipelineId)}/sources`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export async function scanDramaSource(sourceId: string): Promise<DramaScanResult> {
  return dramaFetch<DramaScanResult>(
    `/api/drama/sources/${encodeURIComponent(sourceId)}/scan`,
    { method: "POST" },
  );
}

export async function listDramaSeries(pipelineId: string): Promise<DramaSeriesDto[]> {
  return dramaFetch<DramaSeriesDto[]>(
    `/api/drama/pipelines/${encodeURIComponent(pipelineId)}/series`,
  );
}

export async function getDramaSeries(pipelineId: string, seriesId: string): Promise<DramaSeriesDto> {
  return dramaFetch<DramaSeriesDto>(
    `/api/drama/series/${encodeURIComponent(seriesId)}`,
  );
}

export async function listDramaSeriesEpisodes(
  seriesId: string,
  opts: { limit?: number; offset?: number; status?: string } = {},
): Promise<{ items: DramaEpisodeDto[]; total: number }> {
  const q = new URLSearchParams();
  q.set("limit", String(opts.limit ?? 500));
  q.set("offset", String(opts.offset ?? 0));
  if (opts.status) q.set("status", opts.status);
  return dramaFetch(
    `/api/drama/series/${encodeURIComponent(seriesId)}/episodes?${q.toString()}`,
  );
}

export async function listDramaPipelineInventory(
  pipelineId: string,
  opts: { limit?: number; offset?: number; status?: string } = {},
): Promise<DramaPipelineInventoryDto> {
  const q = new URLSearchParams();
  q.set("limit", String(opts.limit ?? 500));
  q.set("offset", String(opts.offset ?? 0));
  if (opts.status) q.set("status", opts.status);
  return dramaFetch(
    `/api/drama/pipelines/${encodeURIComponent(pipelineId)}/inventory?${q.toString()}`,
  );
}

export async function searchGlobalDramaSeries(
  opts: { query?: string; limit?: number; offset?: number } = {}
): Promise<{ items: DramaSeriesDto[]; total: number }> {
  const q = new URLSearchParams();
  if (opts.query) q.set("query", opts.query);
  if (opts.limit) q.set("limit", String(opts.limit));
  if (opts.offset) q.set("offset", String(opts.offset));
  return dramaFetch(`/api/drama/series?${q.toString()}`);
}
export interface DramaProcessingSettingsDto {
  pipeline_id: string;
  processing_mode: "direct_merge" | "translate_sub" | "dub_vi";
  merge_all_episodes: boolean;
  episodes_per_video: number | null;
  target_language: string | null;
  subtitle_enabled: boolean;
  tts_enabled: boolean;
  template_enabled: boolean;
  template_id: string | null;
  template_mode: string | null;
  youtube_destination_id: string | null;
  auto_publish: boolean;
  total_episodes: number;
  planned_videos: number;
}

export async function getDramaProcessingSettings(
  pipelineId: string,
): Promise<DramaProcessingSettingsDto> {
  return dramaFetch<DramaProcessingSettingsDto>(
    `/api/drama/pipelines/${encodeURIComponent(pipelineId)}/processing-settings`,
  );
}

export async function updateDramaProcessingSettings(
  pipelineId: string,
  payload: {
    processing_mode?: string;
    merge_all_episodes?: boolean;
    episodes_per_video?: number | null;
    target_language?: string | null;
    subtitle_enabled?: boolean;
    tts_enabled?: boolean;
    template_enabled?: boolean;
    template_id?: string | null;
    template_mode?: string | null;
    youtube_destination_id?: string | null;
    auto_publish?: boolean;
  },
): Promise<DramaProcessingSettingsDto> {
  return dramaFetch<DramaProcessingSettingsDto>(
    `/api/drama/pipelines/${encodeURIComponent(pipelineId)}/processing-settings`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export interface DramaTemplateDto {
  id: string;
  name: string;
  asset_url: string;
  canvas_width: number;
  canvas_height: number;
  content_x: number;
  content_y: number;
  content_width: number;
  content_height: number;
}

export async function listDramaTemplates(): Promise<{ items: DramaTemplateDto[] }> {
  return dramaFetch<{ items: DramaTemplateDto[] }>(`/api/drama/templates`);
}

export async function createDramaTemplate(payload: {
  name: string;
  asset_url: string;
  canvas_width?: number;
  canvas_height?: number;
  content_x?: number;
  content_y?: number;
  content_width?: number;
  content_height?: number;
}): Promise<DramaTemplateDto> {
  return dramaFetch<DramaTemplateDto>(`/api/drama/templates`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export interface DramaSeriesJobDto {
  id: string;
  pipeline_id: string;
  series_id: string;
  processing_mode: string;
  chunk_index: number;
  episode_start: number | null;
  episode_end: number | null;
  status: string;
  stage: string | null;
  downloaded_episode_ids: string[];
  output_path: string | null;
  youtube_video_id: string | null;
  last_error_code: string | null;
  last_error_message: string | null;
  upload_progress: number | null;
  template_id: string | null;
}

export async function listDramaPipelineJobs(
  pipelineId: string,
): Promise<{ items: DramaSeriesJobDto[] }> {
  return dramaFetch<{ items: DramaSeriesJobDto[] }>(
    `/api/drama/pipelines/${encodeURIComponent(pipelineId)}/jobs`,
  );
}

export interface DramaEpisodeTaskDto {
  id: string;
  job_id: string;
  episode_id: string;
  episode_number: number;
  status: string;
  render_progress: number | null;
  segment_bytes: number | null;
  duration: number | null;
  attempt_count: number;
  last_error_code: string | null;
  last_error_message: string | null;
}

export async function listDramaJobEpisodes(
  jobId: string,
): Promise<{ items: DramaEpisodeTaskDto[]; counts: Record<string, number> }> {
  return dramaFetch<{ items: DramaEpisodeTaskDto[]; counts: Record<string, number> }>(
    `/api/drama/series-jobs/${encodeURIComponent(jobId)}/episodes`,
  );
}

export async function retryDramaJob(
  jobId: string,
  payload?: { episode_numbers?: number[]; failed_only?: boolean },
): Promise<{ ok: boolean; job_id: string; reset: number }> {
  return dramaFetch<{ ok: boolean; job_id: string; reset: number }>(
    `/api/drama/series-jobs/${encodeURIComponent(jobId)}/retry`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload ?? { failed_only: true }),
    },
  );
}

export interface DramaYoutubeDestinationDto {
  id: string;
  pipeline_id: string;
  channel_id: string | null;
  channel_title: string | null;
  channel_thumbnail: string | null;
  visibility: string;
  enabled: boolean;
  connected: boolean;
  credentials_present?: boolean;
}

export async function listDramaPipelineDestinations(
  pipelineId: string,
): Promise<DramaYoutubeDestinationDto[]> {
  return dramaFetch<DramaYoutubeDestinationDto[]>(
    `/api/drama/pipelines/${encodeURIComponent(pipelineId)}/youtube-destinations`,
  );
}

export async function listDramaConnectedChannels(): Promise<DramaYoutubeDestinationDto[]> {
  return dramaFetch<DramaYoutubeDestinationDto[]>(`/api/drama/youtube/destinations`);
}

export async function startDramaYoutubeOAuth(
  pipelineId: string,
  visibility?: string,
): Promise<{ authorization_url: string; destination_id: string }> {
  const qs = new URLSearchParams({ pipeline_id: pipelineId });
  if (visibility) qs.set("visibility", visibility);
  qs.set("return_to", `/drama/${pipelineId}?tab=youtube`);
  return dramaFetch<{ authorization_url: string; destination_id: string }>(
    `/api/drama/youtube/oauth/start?${qs.toString()}`,
  );
}

export async function disconnectDramaDestination(
  destinationId: string,
): Promise<{ ok: boolean; destination_id: string; connected: boolean }> {
  return dramaFetch<{ ok: boolean; destination_id: string; connected: boolean }>(
    `/api/drama/youtube-destinations/${encodeURIComponent(destinationId)}`,
    { method: "DELETE" },
  );
}
