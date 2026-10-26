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
  visibility: string;
  enabled: boolean;
  connected: boolean;
  connected_at: string | null;
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
  return (process.env.TIKTOK_API_URL ?? "").trim().replace(/\/+$/, "");
}

function adminToken(): string {
  return (process.env.TIKTOK_ADMIN_TOKEN ?? "").trim();
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
  payload: { enabled?: boolean; auto_publish?: boolean; name?: string },
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
}): Promise<TikTokDestinationDto> {
  return ttFetch<TikTokDestinationDto>("/api/tiktok/youtube/destinations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
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

export async function getProviderHealth() {
  return ttFetch<{ provider: string; healthy: boolean; available: string[] }>(
    "/health/providers",
  );
}
