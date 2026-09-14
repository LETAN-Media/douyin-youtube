export interface Pipeline {
  id: string;
  name: string;
  slug: string;
  niche?: string | null;
  language?: string | null;
  fixed_hashtags?: string[] | null;
  adaptive_hashtags?: string[] | null;
  prompt_profile?: string | null;
  default_privacy: string;
  enabled: boolean;
  daily_upload_limit: number;
  upload_slots?: string[] | null;
  backlog_slots_per_day: number;
  new_slots_per_day: number;
  backlog_order: string;
  source_selection_strategy: string;
  backlog_threshold_days: number;
  timezone: string;
  created_at: string;
  updated_at: string;
}

export interface DashboardPipelineRow {
  id: string;
  name: string;
  slug: string;
  enabled: boolean;
  youtube_connected: boolean;
  youtube_channel_title?: string | null;
  sources_count: number;
  destinations_count: number;
  jobs_total: number;
  jobs_published: number;
  jobs_pending: number;
  default_privacy: string;
  inventory_total: number;
  backlog: number;
  new: number;
  scheduled: number;
  published_inventory: number;
  today_published: number;
  publications_total: number;
  publications_failed: number;
  publications_scheduled: number;
  publications_published: number;
  published_today: number;
  failed: number;
  daily_upload_limit: number;
  next_upload?: string | null;
}

export interface PipelineStats {
  pipeline_id: string;
  sources_count: number;
  destinations_count: number;
  inventory_total: number;
  backlog: number;
  new: number;
  scheduled: number;
  published_inventory: number;
  published_today: number;
  failed: number;
  publications_scheduled: number;
  next_publication?: string | null;
}

export interface DouyinSource {
  id: string;
  pipeline_id?: string | null;
  name: string;
  original_profile_url?: string | null;
  profile_url?: string | null;
  douyin_sec_uid?: string | null;
  douyin_user_id?: string | null;
  inventory_sync_status: string;
  inventory_count?: number | null;
  inventory_synced_at?: string | null;
  inventory_sync_error?: string | null;
  enabled: boolean;
  last_video_id?: string | null;
  last_checked_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface InventoryVideo {
  id: string;
  source_id: string;
  pipeline_id: string;
  video_id: string;
  title: string;
  description: string;
  url: string;
  douyin_created_at?: string | null;
  status: string;
  is_backlog: boolean;
  is_backfill?: boolean | null;
  scheduled_at?: string | null;
  published_at?: string | null;
  youtube_video_id?: string | null;
  youtube_url?: string | null;
  created_at: string;
  updated_at: string;
}

export interface InventoryList {
  items: InventoryVideo[];
  total: number;
  page: number;
  page_size: number;
}

export interface Publication {
  id: string;
  pipeline_id: string;
  douyin_video_id: string;
  destination_id: string;
  platform: string;
  status: string;
  scheduled_at?: string | null;
  started_at?: string | null;
  published_at?: string | null;
  external_post_id?: string | null;
  external_url?: string | null;
  title?: string | null;
  description?: string | null;
  attempts: number;
  error?: string | null;
  created_at: string;
  updated_at: string;
}

export interface VideoWithPublications extends InventoryVideo {
  source_name?: string | null;
  publications: Publication[];
}

export interface Destination {
  id: string;
  pipeline_id: string;
  platform: "youtube" | "facebook" | string;
  name: string;
  external_account_id?: string | null;
  external_account_name?: string | null;
  enabled: boolean;
  connected: boolean;
  daily_upload_limit: number;
  timezone: string;
  upload_slots?: string[] | null;
  publish_strategy: string;
  metadata_language?: string | null;
  metadata_profile?: string | null;
  fixed_hashtags?: string[] | null;
  adaptive_hashtags?: string[] | null;
  prompt_override?: string | null;
  created_at: string;
  updated_at: string;
}

export interface DestinationStatus {
  connected: boolean;
  platform: string;
  name: string;
  daily_upload_limit: number;
  today_published: number;
  next_upload?: string | null;
  enabled: boolean;
}

export interface FlowSource {
  id: string;
  name: string;
  username?: string | null;
  inventory_count: number;
  sync_status: string;
  enabled: boolean;
}

export interface FlowProcessor {
  key: string;
  label: string;
  sub: string;
  state: "idle" | "syncing" | "waiting" | "processing" | "error" | string;
  detail: string;
}

export interface FlowDestination {
  id: string;
  platform: string;
  name: string;
  connected: boolean;
  enabled: boolean;
  today_published: number;
  daily_upload_limit: number;
  next_upload?: string | null;
  last_published_at?: string | null;
}

export interface FlowRoute {
  key: string;
  publication_id?: string | null;
  job_id?: string | null;
  video_id: string;
  video_title: string;
  source_id: string;
  source_name: string;
  destination_id: string;
  destination_name: string;
  platform: string;
  stage: string;
  progress?: number | null;
  attempts: number;
  started_at?: string | null;
  scheduled_at?: string | null;
  error?: string | null;
  failed: boolean;
}

export interface FlowState {
  pipeline_id: string;
  summary: {
    sources: number;
    inventory_total: number;
    queue: number;
    publishing: number;
    failed: number;
  };
  sources: FlowSource[];
  processors: FlowProcessor[];
  destinations: FlowDestination[];
  active_routes: FlowRoute[];
}

export interface YoutubeStatus {
  connected: boolean;
  destination_id?: string | null;
  pipeline_id?: string | null;
  platform?: string | null;
  name?: string | null;
  channel_id?: string | null;
  channel_title?: string | null;
  callback_url?: string | null;
}

export interface Job {
  id: string;
  source_url: string;
  source_title?: string | null;
  title?: string | null;
  description?: string | null;
  privacy_status: string;
  status: string;
  attempts: number;
  progress: number;
  youtube_video_id?: string | null;
  youtube_url?: string | null;
  error?: string | null;
  pipeline_id?: string | null;
  source_video_id?: string | null;
  destination_id?: string | null;
  created_at: string;
  updated_at: string;
}

export type ActionResult = { ok: true } | { ok: false; error: string };

export interface DouyinSessionStatus {
  configured: boolean;
  cookie_configured?: boolean;
  anonymous_access?: boolean | null;
  cookie_required?: boolean | null;
  last_validation?: string | null;
  valid: boolean;
  error?: string | null;
}
