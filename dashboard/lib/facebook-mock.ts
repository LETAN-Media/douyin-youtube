export interface FacebookPipeline {
  pipelineId: string;
  name: string;
  slug: string;
  enabled: boolean;
  sources: number;
  inventory: number;
  destinations: number;
  publishedToday: number;
  dailyLimit: number;
  nextUpload: string | null;
  failed: number;
  publishedTotal: number;
  total: number;
  autoReason: string | null;
}

export interface FacebookSource {
  sourceId: string;
  pipelineId: string;
  platform: "facebook";
  name: string;
  pageId: string;
  pageName: string;
  status: "connected" | "error" | "scanning";
  autoScan: boolean;
  lastScanAt: string | null;
  videosFound: number;
}

export interface FacebookInventoryItem {
  id: string;
  pipelineId: string;
  facebookVideoId: string;
  youtubeVideoId?: string | null;
  title: string;
  thumbnailUrl?: string | null;
  publishedAt?: string | null;
  duration: string;
  status: "new" | "queued" | "processing" | "ready" | "uploaded" | "failed";
}

export interface FacebookPublication {
  id: string;
  pipelineId: string;
  facebookVideoId: string;
  youtubeVideoId: string;
  status: "published" | "failed" | "processing" | "queued";
  publishedAt?: string | null;
  error?: string | null;
}

export interface FacebookAiSettings {
  titleMode: "keep" | "ai_rewrite";
  descriptionMode: "keep" | "ai_generate";
  hashtagsMode: "source" | "ai";
  thumbnailMode: "keep" | "custom";
}

export const FACEBOOK_PIPELINES: FacebookPipeline[] = [
  {
    pipelineId: "fb-daily",
    name: "Facebook Daily",
    slug: "facebook-daily",
    enabled: true,
    sources: 1,
    inventory: 25,
    destinations: 1,
    publishedToday: 3,
    dailyLimit: 6,
    nextUpload: "21:00",
    failed: 0,
    publishedTotal: 24,
    total: 25,
    autoReason: "WAITING_NEXT_SLOT",
  },
  {
    pipelineId: "fb-reels",
    name: "Facebook Reels",
    slug: "facebook-reels",
    enabled: true,
    sources: 2,
    inventory: 40,
    destinations: 2,
    publishedToday: 5,
    dailyLimit: 10,
    nextUpload: "20:00",
    failed: 1,
    publishedTotal: 18,
    total: 40,
    autoReason: "NO_AVAILABLE_INVENTORY",
  },
  {
    pipelineId: "fb-viral",
    name: "Viral Facebook",
    slug: "viral-facebook",
    enabled: false,
    sources: 1,
    inventory: 12,
    destinations: 1,
    publishedToday: 0,
    dailyLimit: 4,
    nextUpload: null,
    failed: 0,
    publishedTotal: 8,
    total: 12,
    autoReason: null,
  },
  {
    pipelineId: "fb-news",
    name: "News Facebook",
    slug: "news-facebook",
    enabled: true,
    sources: 3,
    inventory: 60,
    destinations: 1,
    publishedToday: 2,
    dailyLimit: 8,
    nextUpload: "19:30",
    failed: 0,
    publishedTotal: 45,
    total: 60,
    autoReason: "Auto ON · No videos available",
  },
];

export const FACEBOOK_SOURCES: Record<string, FacebookSource[]> = {
  "fb-daily": [
    {
      sourceId: "fb-daily-src",
      pipelineId: "fb-daily",
      platform: "facebook",
      name: "Vibe Men World",
      pageId: "123456789",
      pageName: "Vibe Men World",
      status: "connected",
      autoScan: true,
      lastScanAt: new Date(Date.now() - 2 * 60 * 1000).toISOString(),
      videosFound: 25,
    },
  ],
  "fb-reels": [
    {
      sourceId: "fb-reels-src-1",
      pipelineId: "fb-reels",
      platform: "facebook",
      name: "Reels Channel A",
      pageId: "111222333",
      pageName: "Reels Channel A",
      status: "connected",
      autoScan: true,
      lastScanAt: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
      videosFound: 22,
    },
    {
      sourceId: "fb-reels-src-2",
      pipelineId: "fb-reels",
      platform: "facebook",
      name: "Reels Channel B",
      pageId: "444555666",
      pageName: "Reels Channel B",
      status: "scanning",
      autoScan: true,
      lastScanAt: new Date(Date.now() - 30 * 1000).toISOString(),
      videosFound: 18,
    },
  ],
  "fb-viral": [
    {
      sourceId: "fb-viral-src",
      pipelineId: "fb-viral",
      platform: "facebook",
      name: "Viral Page",
      pageId: "777888999",
      pageName: "Viral Page",
      status: "error",
      autoScan: false,
      lastScanAt: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
      videosFound: 12,
    },
  ],
  "fb-news": [
    {
      sourceId: "fb-news-src",
      pipelineId: "fb-news",
      platform: "facebook",
      name: "News Daily",
      pageId: "101010101",
      pageName: "News Daily",
      status: "connected",
      autoScan: true,
      lastScanAt: new Date(Date.now() - 1 * 60 * 1000).toISOString(),
      videosFound: 60,
    },
  ],
};

export const FACEBOOK_INVENTORY: Record<string, FacebookInventoryItem[]> = {
  "fb-daily": Array.from({ length: 6 }).map((_, i) => {
    const statuses: FacebookInventoryItem["status"][] = ["new", "queued", "processing", "ready", "uploaded", "failed"];
    const status = statuses[i % statuses.length];
    return {
      id: `fb-daily-inv-${i + 1}`,
      pipelineId: "fb-daily",
      facebookVideoId: `fb_daily_${100 + i}`,
      youtubeVideoId: status === "uploaded" ? `yt_abc_${i}` : null,
      title: `Facebook Daily Video ${i + 1}`,
      thumbnailUrl: null,
      publishedAt: status === "uploaded" ? new Date(Date.now() - i * 3600000).toISOString() : null,
      duration: `${1 + (i % 5)}:${String(10 + i * 3).slice(-2)}`,
      status,
    };
  }),
  "fb-reels": Array.from({ length: 5 }).map((_, i) => ({
    id: `fb-reels-inv-${i + 1}`,
    pipelineId: "fb-reels",
    facebookVideoId: `fb_reels_${200 + i}`,
    youtubeVideoId: i === 0 ? `yt_reels_${i}` : null,
    title: `Reels Clip ${i + 1}`,
    thumbnailUrl: null,
    publishedAt: i === 0 ? new Date(Date.now() - i * 3600000).toISOString() : null,
    duration: `${0 + (i % 3)}:${String(15 + i * 5).slice(-2)}`,
    status: i === 0 ? "uploaded" : i === 1 ? "ready" : "new",
  })),
  "fb-viral": Array.from({ length: 4 }).map((_, i) => ({
    id: `fb-viral-inv-${i + 1}`,
    pipelineId: "fb-viral",
    facebookVideoId: `fb_viral_${300 + i}`,
    youtubeVideoId: null,
    title: `Viral Clip ${i + 1}`,
    thumbnailUrl: null,
    publishedAt: null,
    duration: `${1 + i}:00`,
    status: "new",
  })),
  "fb-news": Array.from({ length: 7 }).map((_, i) => {
    const statuses: FacebookInventoryItem["status"][] = ["new", "queued", "processing", "ready", "uploaded", "failed", "ready"];
    return {
      id: `fb-news-inv-${i + 1}`,
      pipelineId: "fb-news",
      facebookVideoId: `fb_news_${400 + i}`,
      youtubeVideoId: statuses[i] === "uploaded" ? `yt_news_${i}` : null,
      title: `News Segment ${i + 1}`,
      thumbnailUrl: null,
      publishedAt: statuses[i] === "uploaded" ? new Date(Date.now() - i * 3600000).toISOString() : null,
      duration: `${1 + (i % 4)}:${String(20 + i * 2).slice(-2)}`,
      status: statuses[i],
    };
  }),
};

export const FACEBOOK_PUBLICATIONS: Record<string, FacebookPublication[]> = {
  "fb-daily": [
    {
      id: "fb-daily-pub-1",
      pipelineId: "fb-daily",
      facebookVideoId: "fb_daily_100",
      youtubeVideoId: "yt_abc_0",
      status: "published",
      publishedAt: new Date(Date.now() - 3600000).toISOString(),
    },
    {
      id: "fb-daily-pub-2",
      pipelineId: "fb-daily",
      facebookVideoId: "fb_daily_101",
      youtubeVideoId: "yt_abc_1",
      status: "published",
      publishedAt: new Date(Date.now() - 7200000).toISOString(),
    },
    {
      id: "fb-daily-pub-3",
      pipelineId: "fb-daily",
      facebookVideoId: "fb_daily_102",
      youtubeVideoId: "",
      status: "failed",
      publishedAt: null,
      error: "YouTube quota exceeded",
    },
  ],
  "fb-reels": [
    {
      id: "fb-reels-pub-1",
      pipelineId: "fb-reels",
      facebookVideoId: "fb_reels_200",
      youtubeVideoId: "yt_reels_0",
      status: "published",
      publishedAt: new Date(Date.now() - 1800000).toISOString(),
    },
  ],
  "fb-viral": [],
  "fb-news": [
    {
      id: "fb-news-pub-1",
      pipelineId: "fb-news",
      facebookVideoId: "fb_news_400",
      youtubeVideoId: "yt_news_0",
      status: "published",
      publishedAt: new Date(Date.now() - 5400000).toISOString(),
    },
  ],
};

export const FACEBOOK_AI_SETTINGS: Record<string, FacebookAiSettings> = {
  "fb-daily": {
    titleMode: "ai_rewrite",
    descriptionMode: "ai_generate",
    hashtagsMode: "ai",
    thumbnailMode: "keep",
  },
  "fb-reels": {
    titleMode: "keep",
    descriptionMode: "keep",
    hashtagsMode: "source",
    thumbnailMode: "keep",
  },
  "fb-viral": {
    titleMode: "keep",
    descriptionMode: "ai_generate",
    hashtagsMode: "ai",
    thumbnailMode: "custom",
  },
  "fb-news": {
    titleMode: "ai_rewrite",
    descriptionMode: "ai_generate",
    hashtagsMode: "source",
    thumbnailMode: "keep",
  },
};

export const FACEBOOK_DESTINATIONS: Record<string, { id: string; name: string; channelId: string; connected: boolean; autoUpload: boolean; visibility: string; schedule: string }[]> = {
  "fb-daily": [
    {
      id: "fb-daily-yt-1",
      name: "JoyBeat Dance",
      channelId: "UC_mock_channel_1",
      connected: true,
      autoUpload: true,
      visibility: "public",
      schedule: "Auto / Scheduled",
    },
  ],
  "fb-reels": [
    {
      id: "fb-reels-yt-1",
      name: "Reels Channel A",
      channelId: "UC_mock_channel_2",
      connected: true,
      autoUpload: true,
      visibility: "public",
      schedule: "Auto / Scheduled",
    },
  ],
  "fb-viral": [
    {
      id: "fb-viral-yt-1",
      name: "Viral YouTube",
      channelId: "UC_mock_channel_3",
      connected: false,
      autoUpload: false,
      visibility: "private",
      schedule: "Manual",
    },
  ],
  "fb-news": [
    {
      id: "fb-news-yt-1",
      name: "News Daily YT",
      channelId: "UC_mock_channel_4",
      connected: true,
      autoUpload: true,
      visibility: "public",
      schedule: "Auto / Scheduled",
    },
  ],
};

export function getFacebookPipeline(pipelineId: string): FacebookPipeline | undefined {
  return FACEBOOK_PIPELINES.find((p) => p.pipelineId === pipelineId);
}

export function getFacebookSources(pipelineId: string): FacebookSource[] {
  return FACEBOOK_SOURCES[pipelineId] ?? [];
}

export function getFacebookInventory(pipelineId: string): FacebookInventoryItem[] {
  return FACEBOOK_INVENTORY[pipelineId] ?? [];
}

export function getFacebookPublications(pipelineId: string): FacebookPublication[] {
  return FACEBOOK_PUBLICATIONS[pipelineId] ?? [];
}

export function getFacebookAiSettings(pipelineId: string): FacebookAiSettings {
  return FACEBOOK_AI_SETTINGS[pipelineId] ?? {
    titleMode: "keep",
    descriptionMode: "keep",
    hashtagsMode: "source",
    thumbnailMode: "keep",
  };
}

export function getFacebookDestinations(pipelineId: string) {
  return FACEBOOK_DESTINATIONS[pipelineId] ?? [];
}
