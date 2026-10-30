// Server-side YouTube→Facebook backend client. Never import from client components.
// The admin token stays on the server; the browser polls these Next.js proxy routes.

export interface YoutTubeFbApiError extends Error {
  status: number;
}

export interface YtFbPipeline {
  id: string;
  name: string;
  description: string | null;
  status: string;
  ordering: string;
  max_daily_publish: number;
  timezone: string;
  publish_slots: string[];
  slot_window_minutes: number;
  slot_max_daily: number;
  min_interval_minutes: number;
  auto_scan: boolean;
  auto_publish: boolean;
  next_scan_at: string | null;
  youtube_channel_id: string | null;
  youtube_channel_title: string | null;
  ai_strategy: string;
  ai_model: string | null;
  ai_max_tokens?: number | null;
  default_publish_mode: string;
  default_facebook_page_id: string | null;
  created_at: string;
  updated_at: string;
  video_count: number | null;
}

export interface YtFbSource {
  id: string;
  pipeline_id: string;
  source_type: string;
  channel_id: string | null;
  channel_title: string | null;
  playlist_id: string | null;
  custom_url: string | null;
  status: string;
  last_scan_at: string | null;
  last_scan_error: string | null;
  created_at: string;
}

export interface YtFbFacebookPage {
  id: string;
  pipeline_id: string;
  page_id: string;
  page_name: string | null;
  scopes: string[] | null;
  is_default: boolean;
  status: string;
  error: string | null;
  synced_at: string | null;
  created_at: string;
}

export interface YtFbVideo {
  pipeline_id: string;
  video_id: string;
  channel_id: string | null;
  title: string | null;
  description: string | null;
  duration_seconds: number | null;
  publish_time: string | null;
  thumbnail_url: string | null;
  view_count: number | null;
  like_count: number | null;
  created_at: string;
}

export interface YtFbQueueItem {
  id: string;
  pipeline_id: string;
  youtube_video_id: string;
  facebook_page_id: string;
  media_file_id: string;
  schedule_id: string | null;
  status: string;
  priority: number;
  scheduled_for: string | null;
  retry_count: number;
  publish_mode: string;
  ai_caption: string | null;
  ai_enhanced: boolean;
  title: string | null;
  description: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface YtFbPublication {
  id: string;
  pipeline_id: string;
  youtube_video_id: string;
  facebook_page_id: string;
  media_file_id: string | null;
  facebook_post_id: string | null;
  facebook_video_id: string | null;
  facebook_reel_id: string | null;
  publish_mode: string;
  status: string;
  ai_caption: string | null;
  ai_enhanced: boolean;
  title: string | null;
  description: string | null;
  published_at: string | null;
  created_at: string;
}

export interface YtFbSchedule {
  id: string;
  pipeline_id: string;
  scheduled_date: string;
  slot_index: number;
  slot_time: string;
  slot_max_daily: number;
  publish_count: number;
  reserved_count: number;
  is_active: boolean;
  created_at: string;
}

export interface YtFbScanResult {
  scanned: number;
  new: number;
  sources: { id: string; channel_id: string | null }[];
}

export interface YtFbManualResult {
  status: string;
  video_id: string;
  queue_item_id?: string;
  scheduled_for?: string | null;
  result?: Record<string, unknown>;
}

export interface YtFbHealth {
  status: string;
  service: string;
  version: string;
}

export interface YtFbPipelineCreate {
  name: string;
  description?: string | null;
  timezone?: string;
  ordering?: string;
  max_daily_publish?: number;
  publish_slots?: string[];
  slot_window_minutes?: number;
  slot_max_daily?: number;
  min_interval_minutes?: number;
  auto_scan?: boolean;
  auto_publish?: boolean;
  youtube_channel_id?: string | null;
  ai_strategy?: string;
  ai_model?: string | null;
  default_publish_mode?: string;
  default_facebook_page_id?: string | null;
  settings?: Record<string, unknown> | null;
}

export interface YtFbPipelineUpdate {
  name?: string;
  description?: string | null;
  status?: string;
  ordering?: string;
  max_daily_publish?: number;
  timezone?: string;
  publish_slots?: string[];
  slot_window_minutes?: number;
  slot_max_daily?: number;
  min_interval_minutes?: number;
  auto_scan?: boolean;
  auto_publish?: boolean;
  next_scan_at?: string | null;
  youtube_channel_id?: string | null;
  ai_strategy?: string;
  ai_model?: string | null;
  ai_max_tokens?: number;
  ai_temperature?: number;
  default_publish_mode?: string;
  default_facebook_page_id?: string | null;
}

export interface YtFbSourceCreate {
  source_type?: string;
  channel_id?: string | null;
  channel_title?: string | null;
  playlist_id?: string | null;
  custom_url?: string | null;
}

export interface YtFbPageCreate {
  page_id: string;
  page_name?: string | null;
  page_access_token?: string | null;
  scopes?: string[] | null;
  is_default?: boolean;
}

export interface YtFbManualRequest {
  youtube_url: string;
  facebook_page_id: string;
  publish_mode?: string;
  caption?: string | null;
  title?: string | null;
  description?: string | null;
  schedule_for?: string | null;
  use_ai_caption?: boolean;
}

function baseUrl(): string {
  return (process.env.YOUTUBE_FB_API_URL ?? "").trim().replace(/\/+$/, "");
}

function adminToken(): string {
  return (process.env.YOUTUBE_FB_ADMIN_TOKEN ?? "").trim();
}

export function requireYtFbEnv(): { base: string; token: string } {
  const base = baseUrl();
  if (!base) {
    const err: YoutTubeFbApiError = new Error(
      "YOUTUBE_FB_API_URL chưa được cấu hỉnh.",
    ) as YoutTubeFbApiError;
    err.status = 500;
    throw err;
  }
  const token = adminToken();
  if (!token || token === "CHANGE_ME_LONG_RANDOM_TOKEN") {
    const err: YoutTubeFbApiError = new Error(
      "YOUTUBE_FB_ADMIN_TOKEN chưa được cấu hình.",
    ) as YoutTubeFbApiError;
    err.status = 500;
    throw err;
  }
  return { base, token };
}

export async function ytFbFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const { base, token } = requireYtFbEnv();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30000);
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
      const err: YoutTubeFbApiError = new Error(
        "YouTube→Facebook backend authentication failed.",
      ) as YoutTubeFbApiError;
      err.status = 401;
      throw err;
    }
    if (res.status === 404) {
      const err: YoutTubeFbApiError = new Error("Không tìm thấy resource.") as YoutTubeFbApiError;
      err.status = 404;
      throw err;
    }
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      let detail: unknown = text;
      try {
        detail = JSON.parse(text);
      } catch {
        // keep raw text
      }
      const message =
        typeof detail === "string"
          ? detail
          : (detail as Record<string, unknown>)?.message ||
            (detail as Record<string, unknown>)?.error ||
            "Backend YouTube→Facebook gặp lỗi.";
      const err: YoutTubeFbApiError = new Error(String(message)) as YoutTubeFbApiError;
      err.status = res.status;
      throw err;
    }
    if (res.status === 204 || res.headers.get("content-length") === "0") {
      return undefined as unknown as T;
    }
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

export const ytFb = {
  async listPipelines(): Promise<YtFbPipeline[]> {
    return ytFbFetch<YtFbPipeline[]>("/api/youtube-fb/pipelines");
  },
  async createPipeline(payload: YtFbPipelineCreate): Promise<YtFbPipeline> {
    return ytFbFetch<YtFbPipeline>("/api/youtube-fb/pipelines", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  async getPipeline(id: string): Promise<YtFbPipeline> {
    return ytFbFetch<YtFbPipeline>(`/api/youtube-fb/pipelines/${encodeURIComponent(id)}`);
  },
  async updatePipeline(id: string, payload: YtFbPipelineUpdate): Promise<YtFbPipeline> {
    return ytFbFetch<YtFbPipeline>(`/api/youtube-fb/pipelines/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },
  async deletePipeline(id: string): Promise<void> {
    return ytFbFetch<void>(`/api/youtube-fb/pipelines/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
  },
  async listSources(pipelineId: string): Promise<YtFbSource[]> {
    return ytFbFetch<YtFbSource[]>(`/api/youtube-fb/pipelines/${encodeURIComponent(pipelineId)}/sources`);
  },
  async addSource(pipelineId: string, payload: YtFbSourceCreate): Promise<YtFbSource> {
    return ytFbFetch<YtFbSource>(`/api/youtube-fb/pipelines/${encodeURIComponent(pipelineId)}/sources`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  async deleteSource(pipelineId: string, sourceId: string): Promise<void> {
    return ytFbFetch<void>(
      `/api/youtube-fb/pipelines/${encodeURIComponent(pipelineId)}/sources/${encodeURIComponent(sourceId)}`,
      { method: "DELETE" },
    );
  },
  async listVideos(pipelineId: string, limit = 50, offset = 0): Promise<YtFbVideo[]> {
    return ytFbFetch<YtFbVideo[]>(
      `/api/youtube-fb/pipelines/${encodeURIComponent(pipelineId)}/videos?limit=${limit}&offset=${offset}`,
    );
  },
  async listFacebookPages(pipelineId: string): Promise<YtFbFacebookPage[]> {
    return ytFbFetch<YtFbFacebookPage[]>(
      `/api/youtube-fb/pipelines/${encodeURIComponent(pipelineId)}/facebook-pages`,
    );
  },
  async addFacebookPage(pipelineId: string, payload: YtFbPageCreate): Promise<YtFbFacebookPage> {
    return ytFbFetch<YtFbFacebookPage>(
      `/api/youtube-fb/pipelines/${encodeURIComponent(pipelineId)}/facebook-pages`,
      { method: "POST", body: JSON.stringify(payload) },
    );
  },
  async setDefaultFacebookPage(pipelineId: string, pageRowId: string): Promise<{ ok: boolean }> {
    return ytFbFetch<{ ok: boolean }>(
      `/api/youtube-fb/pipelines/${encodeURIComponent(pipelineId)}/facebook-pages/set-default`,
      { method: "POST", body: JSON.stringify({ page_row_id: pageRowId }) },
    );
  },
  async listQueue(pipelineId: string, status?: string): Promise<YtFbQueueItem[]> {
    const qs = status ? `?status=${encodeURIComponent(status)}` : "";
    return ytFbFetch<YtFbQueueItem[]>(
      `/api/youtube-fb/pipelines/${encodeURIComponent(pipelineId)}/queue${qs}`,
    );
  },
  async listHistory(pipelineId: string, limit = 50, offset = 0): Promise<YtFbPublication[]> {
    return ytFbFetch<YtFbPublication[]>(
      `/api/youtube-fb/pipelines/${encodeURIComponent(pipelineId)}/history?limit=${limit}&offset=${offset}`,
    );
  },
  async listSchedules(pipelineId: string, date?: string): Promise<YtFbSchedule[]> {
    const qs = date ? `?date=${encodeURIComponent(date)}` : "";
    return ytFbFetch<YtFbSchedule[]>(
      `/api/youtube-fb/pipelines/${encodeURIComponent(pipelineId)}/schedules${qs}`,
    );
  },
  async triggerScan(pipelineId: string, payload?: { source_ids?: string[]; full_rescan?: boolean }): Promise<YtFbScanResult> {
    return ytFbFetch<YtFbScanResult>(
      `/api/youtube-fb/pipelines/${encodeURIComponent(pipelineId)}/scan`,
      { method: "POST", body: JSON.stringify(payload ?? {}) },
    );
  },
  async manualPublish(pipelineId: string, payload: YtFbManualRequest): Promise<YtFbManualResult> {
    return ytFbFetch<YtFbManualResult>(
      `/api/youtube-fb/pipelines/${encodeURIComponent(pipelineId)}/manual`,
      { method: "POST", body: JSON.stringify(payload) },
    );
  },
  async health(): Promise<YtFbHealth> {
    return ytFbFetch<YtFbHealth>("/api/youtube-fb/health");
  },
};
