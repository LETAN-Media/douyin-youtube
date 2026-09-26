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
  inventory_available?: number | null;
  connected_destinations?: number | null;
  auto_reason?: string | null;
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
  publication_mode?: string | null;
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

export type YouTubePublishMode = "immediate" | "scheduled" | "private" | "unlisted";

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
  youtube_default_publish_mode?: YouTubePublishMode | null;
  upload_slots?: string[] | null;
  publish_strategy: string;
  metadata_language?: string | null;
  metadata_profile?: string | null;
  fixed_hashtags?: string[] | null;
  adaptive_hashtags?: string[] | null;
  prompt_override?: string | null;
  last_scheduler_check_at?: string | null;
  last_cycle_at?: string | null;
  last_job_created_at?: string | null;
  last_skip_reason?: string | null;
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
  mode?: "auto" | "manual" | string | null;
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

export interface ManualResolveResult {
  type: "video" | "profile";
  source_url: string;
  video_id?: string | null;
  author?: string | null;
  author_name?: string | null;
  caption?: string | null;
  thumbnail?: string | null;
  duration?: number | null;
  status: string;
  message?: string | null;
  profile_url?: string | null;
  sec_uid?: string | null;
}

export interface ManualMetadataItem {
  title: string;
  description: string;
  hashtags: string[];
  final_description: string;
  content_match?: boolean | null;
  content_match_reason?: string | null;
  match_level?: "match" | "borderline" | "mismatch" | null;
}

export interface ManualMetadataResult {
  metadata_mode: "same" | "separate";
  same?: ManualMetadataItem | null;
  by_destination: Record<string, ManualMetadataItem>;
}

export interface ManualPublishPayload {
  source_url: string;
  source_title?: string | null;
  video_id?: string | null;
  thumbnail?: string | null;
  duration?: number | null;
  destination_ids: string[];
  metadata_mode: "same" | "separate";
  title?: string | null;
  description?: string | null;
  destinations_metadata?: Record<string, { title: string; description: string }>;
  privacy_status: "public" | "unlisted" | "private";
  force_duplicate?: boolean;
  youtube_publish_mode?: YouTubePublishMode | null;
  youtube_publish_at?: string | null;
  youtube_publish_date?: string | null;
  youtube_publish_time?: string | null;
  youtube_schedule_timezone?: string | null;
}

export interface UpcomingItem {
  publication_id: string;
  destination_id: string;
  video_title?: string | null;
  thumbnail?: string | null;
  youtube_video_id?: string | null;
  external_url?: string | null;
  status: string;
  youtube_publish_mode?: string | null;
  youtube_publish_at?: string | null;
  youtube_schedule_timezone?: string | null;
  youtube_scheduled?: boolean | null;
  preview?: string | null;
}

export interface ManualPublicationItem {
  id: string;
  destination_id: string;
  destination_name: string;
  platform: string;
  status: string;
  progress: number;
  video_title?: string | null;
  source_url?: string | null;
  thumbnail?: string | null;
  external_url?: string | null;
  error?: string | null;
  created_at: string;
  published_at?: string | null;
}

export interface ManualPublishResponse {
  accepted: boolean;
  publications: ManualPublicationItem[];
}

export interface ChannelItem {
  id: string;
  destination_id: string;
  pipeline_id: string;
  pipeline_name: string;
  channel_id?: string | null;
  channel_title: string;
  avatar_url?: string | null;
  connected: boolean;
  enabled: boolean;
  published_today: number;
  queue_count: number;
  last_published_at?: string | null;
}

export interface ChannelSourceItem {
  id: string;
  name: string;
  profile_url?: string | null;
  status: string;
  video_count: number;
  last_synced_at?: string | null;
}

export interface WorkspaceSourceItem extends ChannelSourceItem {
  enabled?: boolean;
  cookie_configured?: boolean;
  cookie_status?: string | null;
  cookie_account_name?: string | null;
  cookie_verified_at?: string | null;
  needs_reauth?: boolean;
  scan_interval_minutes?: number | null;
  max_videos_per_day?: number | null;
  next_scan_at?: string | null;
  last_scan_at?: string | null;
  inventory_sync_error?: string | null;
  // Manual-inventory mode (admin-driven Douyin discovery).
  feed_provider?: string | null;
  initial_import_status?: string | null;
  initial_import_cursor?: string | null;
  initial_import_pages?: number | null;
  initial_import_videos?: number | null;
  initial_import_last_error?: string | null;
  initial_import_started_at?: string | null;
  initial_import_completed_at?: string | null;
  last_refresh_at?: string | null;
  provider_status?: string | null;
  provider_status_detail?: string | null;
}

export interface DouyinQuotaStatus {
  limit: number;
  remaining: number;
  used: number;
  month?: string | null;
  reset_at?: string | null;
  status: "ok" | "low" | "quota_exhausted" | string;
  exhausted: boolean;
  safety_margin: number;
  source?: string | null;
  last_error?: string | null;
  updated_at?: string | null;
}

export interface SourceImportResult {
  source_id: string;
  status: string;
  new: number;
  updated: number;
  pages: number;
  videos: number;
  cursor?: string | null;
  error?: string | null;
  quota?: DouyinQuotaStatus | null;
}

export interface SourceCookieStatus {
  configured: boolean;
  status: string;
  account_name?: string | null;
  verified_at?: string | null;
  needs_reauth: boolean;
}

export interface SourceCookieTestResult {
  ok: boolean;
  nickname?: string | null;
  sec_uid?: string | null;
  latest_aweme_id?: string | null;
}

export interface ChannelAutoStatus {
  auto_enabled: boolean;
  sources_count: number;
  enabled_sources: number;
  needs_reauth_sources: number;
  last_scan_at?: string | null;
  next_scan_at?: string | null;
  today_published: number;
  today_limit: number;
  queue_count: number;
  failed_count: number;
  held_count: number;
  rejected_count: number;
}

export interface ChannelPipelineInfo {
  id: string;
  name: string;
  slug: string;
  enabled: boolean;
  default_privacy: string;
  daily_upload_limit: number;
  upload_slots: string[];
}

export interface ChannelInventoryItem {
  id: string;
  video_id: string;
  title: string;
  description: string;
  thumbnail_url?: string | null;
  url: string;
  status: string;
  is_backlog: boolean;
  douyin_created_at?: string | null;
  created_at?: string | null;
}

export interface ChannelDetail {
  channel: ChannelItem;
  daily_upload_limit: number;
  metadata_profile?: string | null;
  metadata_language?: string | null;
  fixed_hashtags?: string[] | string | null;
  adaptive_hashtags?: string[] | boolean | null;
  prompt_override?: string | null;
  timezone: string;
  youtube_default_publish_mode?: YouTubePublishMode | string | null;
  upload_slots?: string[] | null;
  pipeline: ChannelPipelineInfo;
  sources: ChannelSourceItem[];
  queue: ManualPublicationItem[];
  published: ManualPublicationItem[];
  inventory?: ChannelInventoryItem[];
  inventory_count?: number;
  failed_count?: number;
  next_slot?: string | null;

  // AI Comment Reply — a separate subsystem from all metadata fields above.
  comment_reply_enabled?: boolean;
  comment_reply_mode?: string;
  comment_reply_system_prompt?: string | null;
  comment_reply_language?: string;
  comment_reply_style?: string;
  comment_reply_daily_limit?: number;
  comment_reply_min_interval_seconds?: number;
  comment_reply_new_only?: boolean;
  comment_reply_to_positive?: boolean;
  comment_reply_to_questions?: boolean;
  comment_reply_to_neutral?: boolean;
  comment_reply_to_negative?: boolean;
  comment_reply_to_emoji_only?: boolean;
  comment_reply_to_funny?: boolean;
  comment_reply_to_excited?: boolean;
  comment_oauth_ready?: boolean;
  comment_oauth_reason?: string | null;
  comment_replies_today?: number;
  comment_count?: number;
}

export type CommentReplyMode = "off" | "review" | "auto";

export interface CommentReplySettings {
  destination_id: string;
  enabled: boolean;
  mode: CommentReplyMode;
  system_prompt?: string | null;
  language: string;
  style: string;
  daily_limit: number;
  min_interval_seconds: number;
  new_only: boolean;
  reply_to_positive: boolean;
  reply_to_questions: boolean;
  reply_to_neutral: boolean;
  reply_to_negative: boolean;
  reply_to_emoji_only: boolean;
  reply_to_funny: boolean;
  reply_to_excited: boolean;
  default_system_prompt?: string;
  last_scan_at?: string | null;
  replies_today: number;
  oauth_ready: boolean;
  oauth_reason?: string | null;
}

export interface CommentReplySettingsUpdate {
  enabled?: boolean;
  mode?: CommentReplyMode;
  system_prompt?: string | null;
  language?: string;
  style?: string;
  daily_limit?: number;
  min_interval_seconds?: number;
  new_only?: boolean;
  reply_to_positive?: boolean;
  reply_to_questions?: boolean;
  reply_to_neutral?: boolean;
  reply_to_negative?: boolean;
  reply_to_emoji_only?: boolean;
  reply_to_funny?: boolean;
  reply_to_excited?: boolean;
}

export interface YouTubeComment {
  id: string;
  destination_id: string;
  video_id: string;
  video_title?: string | null;
  youtube_comment_id: string;
  parent_comment_id?: string | null;
  author_channel_id?: string | null;
  author_name?: string | null;
  text_original: string;
  published_at?: string | null;
  like_count: number;
  status: string;
  reply_status: string;
  ai_classification?: string | null;
  ai_reply?: string | null;
  reply_text?: string | null;
  ai_confidence?: number | null;
  ai_reason?: string | null;
  detected_language?: string | null;
  replied_at?: string | null;
  youtube_reply_id?: string | null;
  error?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CommentListResponse {
  destination_id: string;
  total: number;
  items: YouTubeComment[];
  stats: Record<string, number>;
  replies_today: number;
  daily_limit: number;
  mode: string;
  oauth_ready: boolean;
  oauth_reason?: string | null;
}

export interface CommentActionResult {
  ok: boolean;
  comment?: YouTubeComment | null;
  error?: string | null;
}

