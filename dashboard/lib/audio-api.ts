export class AudioApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function baseUrl(): string {
  return (process.env.AUDIO_API_URL ?? "")
    .trim()
    .replace(/\/+$/, "")
    .replace(/\/api\/audio$/, "");
}

function adminToken(): string {
  return (process.env.AUDIO_API_TOKEN ?? "").trim();
}

function requireEnv(): { base: string; token: string } {
  const base = baseUrl();
  if (!base) throw new AudioApiError(500, "AUDIO_API_URL chưa được cấu hình.");
  const token = adminToken();
  if (!token) throw new AudioApiError(500, "AUDIO_API_TOKEN chưa được cấu hình.");
  return { base, token };
}

async function audioFetch<T>(
  path: string,
  init: RequestInit = {},
  timeoutMs = 20000,
): Promise<T> {
  const { base, token } = requireEnv();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${base}${path}`, {
      ...init,
      headers: { "X-Admin-Token": token, ...(init.headers ?? {}) },
      cache: "no-store",
      signal: controller.signal,
    });
    if (res.status === 401) {
      throw new AudioApiError(401, "Audio backend authentication failed.");
    }
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      let message = `Audio backend HTTP ${res.status}.`;
      try {
        const detail = JSON.parse(text) as { message?: string; error?: string };
        message = detail.message || detail.error || message;
      } catch {
        if (text) message = text.slice(0, 300);
      }
      throw new AudioApiError(res.status, message);
    }
    return (await res.json()) as T;
  } catch (err) {
    if (err instanceof AudioApiError) throw err;
    throw new AudioApiError(503, "Không kết nối được audio backend.");
  } finally {
    clearTimeout(timer);
  }
}

export interface AudioPipelineDto {
  id: string;
  name: string;
  slug: string;
  enabled: boolean;
  auto_publish: boolean;
  total_sources: number;
  pending_videos: number;
  published_videos: number;
  running_jobs: number;
  failed_jobs: number;
  last_publish: { youtube_url: string; published_at: string } | null;
}

export interface AudioSourceDto {
  id: string;
  pipeline_id: string;
  url: string;
  canonical_url: string;
  page_name: string | null;
  enabled: boolean;
  last_scanned_at: string | null;
  scan: { state: string; found: number; added: number; error: string | null } | null;
}

export interface AudioInventoryItemDto {
  id: string;
  source_id: string | null;
  facebook_video_id: string | null;
  canonical_url: string;
  thumbnail_url: string | null;
  duration_seconds: number | null;
  caption: string | null;
  status: string;
}

export interface AudioDestinationDto {
  id: string;
  pipeline_id: string;
  channel_id: string | null;
  channel_title: string | null;
  channel_thumbnail: string | null;
  visibility: string;
  enabled: boolean;
  connected: boolean;
}

export interface AudioAssetDto {
  id: string;
  pipeline_id: string;
  kind: string;
  object_key: string;
  file_name: string | null;
  mime: string | null;
  duration_seconds: number | null;
  bytes: number | null;
  enabled: boolean;
  preview_url?: string | null;
}

export interface AudioJobDto {
  id: string;
  pipeline_id: string;
  inventory_id: string | null;
  mode: string;
  status: string;
  stage: string;
  progress_percent: number;
  youtube_video_id: string | null;
  youtube_url: string | null;
  last_error_code: string | null;
  last_error_message: string | null;
  ai_title: string | null;
}

export interface AudioAiSettingsDto {
  pipeline_id: string;
  enabled: boolean;
  language: string;
  genre: string | string[] | null;
  generate_title: boolean;
  generate_description: boolean;
  generate_hashtags: boolean;
  system_prompt: string | null;
  title_template: string | null;
  description_template: string | null;
  locked_hashtags: string[];
  model_override: string | null;
  config_version: number;
  updated_at: string | null;
  genres?: string[];
}

export interface AudioSchedulerDto {
  pipeline_id: string;
  enabled: boolean;
  destination_id: string | null;
  max_videos_per_day: number;
  min_gap_minutes: number;
  timezone: string;
  daily_times: string[];
  order_mode: string;
  rotate_sources: boolean;
  next_run_at: string | null;
  last_run_at: string | null;
  due: boolean;
  due_reason: string;
}

export async function listAudioPipelines(): Promise<{ items: AudioPipelineDto[] }> {
  return audioFetch<{ items: AudioPipelineDto[] }>("/api/audio/pipelines");
}

export async function createAudioPipeline(name: string): Promise<AudioPipelineDto> {
  return audioFetch<AudioPipelineDto>("/api/audio/pipelines", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export async function getAudioPipeline(pipelineId: string): Promise<AudioPipelineDto> {
  return audioFetch<AudioPipelineDto>(
    `/api/audio/pipelines/${encodeURIComponent(pipelineId)}`);
}

export async function updateAudioPipeline(
  pipelineId: string, payload: Record<string, unknown>,
): Promise<AudioPipelineDto> {
  return audioFetch<AudioPipelineDto>(
    `/api/audio/pipelines/${encodeURIComponent(pipelineId)}`,
    { method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload) });
}

export async function deleteAudioPipeline(pipelineId: string): Promise<void> {
  await audioFetch(`/api/audio/pipelines/${encodeURIComponent(pipelineId)}`,
    { method: "DELETE" });
}

export async function listAudioSources(
  pipelineId: string,
): Promise<{ items: AudioSourceDto[] }> {
  return audioFetch(
    `/api/audio/pipelines/${encodeURIComponent(pipelineId)}/sources`);
}

export async function addAudioSources(
  pipelineId: string, urls: string,
): Promise<{ added: unknown[]; existing: unknown[]; invalid: unknown[] }> {
  return audioFetch(
    `/api/audio/pipelines/${encodeURIComponent(pipelineId)}/sources`,
    { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ urls }) });
}

export async function listAudioInventory(
  pipelineId: string, status?: string,
): Promise<{ items: AudioInventoryItemDto[]; total: number }> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  return audioFetch(
    `/api/audio/pipelines/${encodeURIComponent(pipelineId)}/inventory${qs}`);
}

export async function listAudioDestinations(
  pipelineId: string,
): Promise<AudioDestinationDto[]> {
  return audioFetch(
    `/api/audio/pipelines/${encodeURIComponent(pipelineId)}/youtube-destinations`);
}

export async function startAudioOAuth(
  pipelineId: string,
): Promise<{ authorization_url: string; destination_id: string }> {
  return audioFetch(
    `/api/audio/youtube/oauth/start?pipeline_id=${encodeURIComponent(pipelineId)}`,
    { method: "POST" });
}

export async function listAudioMedia(
  pipelineId: string, kind?: string,
): Promise<{ items: AudioAssetDto[] }> {
  const qs = kind ? `?kind=${encodeURIComponent(kind)}` : "";
  return audioFetch(
    `/api/audio/pipelines/${encodeURIComponent(pipelineId)}/media${qs}`);
}

export async function getAudioAiSettings(
  pipelineId: string,
): Promise<AudioAiSettingsDto> {
  return audioFetch(
    `/api/audio/pipelines/${encodeURIComponent(pipelineId)}/ai-settings`);
}

export async function updateAudioAiSettings(
  pipelineId: string, payload: Record<string, unknown>,
): Promise<AudioAiSettingsDto> {
  return audioFetch(
    `/api/audio/pipelines/${encodeURIComponent(pipelineId)}/ai-settings`,
    { method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload) });
}

export async function getAudioScheduler(
  pipelineId: string,
): Promise<AudioSchedulerDto> {
  return audioFetch(
    `/api/audio/pipelines/${encodeURIComponent(pipelineId)}/scheduler`);
}

export async function updateAudioScheduler(
  pipelineId: string, payload: Record<string, unknown>,
): Promise<AudioSchedulerDto> {
  return audioFetch(
    `/api/audio/pipelines/${encodeURIComponent(pipelineId)}/scheduler`,
    { method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload) });
}

export async function listAudioJobs(
  pipelineId: string,
): Promise<{ items: AudioJobDto[] }> {
  return audioFetch(
    `/api/audio/pipelines/${encodeURIComponent(pipelineId)}/jobs`);
}

export async function getAudioProcessingSettings(
  pipelineId: string,
): Promise<Record<string, unknown>> {
  return audioFetch(
    `/api/audio/pipelines/${encodeURIComponent(pipelineId)}/processing-settings`);
}

export async function updateAudioProcessingSettings(
  pipelineId: string, payload: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  return audioFetch(
    `/api/audio/pipelines/${encodeURIComponent(pipelineId)}/processing-settings`,
    { method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload) });
}
