"use client";

import { useState, useTransition, useCallback, useRef, useEffect } from "react";
import Link from "next/link";
import { Badge, Card, ProgressBar } from "@/components/ui";
import {
  IconAlert,
  IconBack,
  IconCheck,
  IconClock,
  IconDashboard,
  IconInventory,
  IconPlus,
  IconPublications,
  IconRefresh,
  IconSettings,
  IconSources,
  IconSparkles,
  IconUpload,
  IconX,
} from "@/components/icons";
import type {
  ChannelAutoStatus,
  ChannelDetail,
  ChannelInventoryItem,
  CommentListResponse,
  CommentReplyMode,
  DouyinQuotaStatus,
  ManualMetadataResult,
  ManualPublicationItem,
  ManualPublishPayload,
  ManualPublishResponse,
  ManualResolveResult,
  WorkspaceSourceItem,
  YouTubeComment,
} from "@/lib/types";
import { actionGetOauthUrl, actionToggleDestination, actionUpdateDestination } from "@/lib/actions";
import { YouTubePublishSelector } from "@/components/YouTubePublishSelector";
import { UpcomingScheduled } from "@/components/UpcomingScheduled";
import { ChannelAnalytics } from "@/components/ChannelAnalytics";
import { ChannelResearch } from "@/components/ChannelResearch";
import { ChannelDNA } from "@/components/ChannelDNA";

function formatDuration(sec?: number | null): string {
  if (sec == null || sec <= 0) return "00:00";
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

function formatTime(isoStr?: string | null): string {
  if (!isoStr) return "--:--";
  try {
    const d = new Date(isoStr);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return isoStr;
  }
}

type TabType =
  | "overview"
  | "manual"
  | "auto"
  | "sources"
  | "inventory"
  | "queue"
  | "upcoming"
  | "published"
  | "analytics"
  | "research"
  | "dna"
  | "comments"
  | "ai_profile"
  | "settings";

interface ChannelWorkspaceClientProps {
  initialDetail: ChannelDetail;
}

export function ChannelWorkspaceClient({ initialDetail }: ChannelWorkspaceClientProps) {
  const [detail, setDetail] = useState<ChannelDetail>(initialDetail);
  const [activeTab, setActiveTab] = useState<TabType>("overview");
  const [pending, startTransition] = useTransition();

  const channel = detail.channel;
  const isConnected = channel.connected;

  // Refresh full channel detail
  const reloadDetail = useCallback(async () => {
    try {
      const res = await fetch(`/api/channels/${channel.destination_id}`);
      if (res.ok) {
        const updated: ChannelDetail = await res.json();
        setDetail(updated);
      }
    } catch (e) {
      console.error("Failed to reload channel detail:", e);
    }
  }, [channel.destination_id]);

  // ==========================================
  // TAB: MANUAL PUBLISH STATE
  // ==========================================
  const [input, setInput] = useState("");
  const [resolving, setResolving] = useState(false);
  const [resolveError, setResolveError] = useState<string | null>(null);
  const [resolvedVideo, setResolvedVideo] = useState<ManualResolveResult | null>(null);
  const [profileDetected, setProfileDetected] = useState<ManualResolveResult | null>(null);

  const [privacy, setPrivacy] = useState<"public" | "unlisted" | "private">("public");
  const [publishMode, setPublishMode] = useState<"immediate" | "scheduled" | "private" | "unlisted">("immediate");
  const [schedDate, setSchedDate] = useState("");
  const [schedTime, setSchedTime] = useState("");
  const [schedTz, setSchedTz] = useState("Asia/Ho_Chi_Minh");
  const [generateAi, setGenerateAi] = useState(true);

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [hashtags, setHashtags] = useState("");
  const [coreHashtags, setCoreHashtags] = useState<string[]>([]);
  const [dynamicHashtags, setDynamicHashtags] = useState<string[]>([]);
  const [generatingMetadata, setGeneratingMetadata] = useState(false);
  const [metadataError, setMetadataError] = useState<string | null>(null);
  const [contentMatchNotice, setContentMatchNotice] = useState<{ match: boolean; level: "match" | "borderline" | "mismatch"; reason: string } | null>(null);

  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);
  const [duplicateWarning, setDuplicateWarning] = useState<{
    message: string;
    external_url?: string;
  } | null>(null);

  const [activePublications, setActivePublications] = useState<ManualPublicationItem[]>([]);

  // Generate metadata helper using this channel's AI profile
  const triggerAiMetadata = useCallback(
    async (sourceUrl: string, captionText: string) => {
      setGeneratingMetadata(true);
      setMetadataError(null);
      setContentMatchNotice(null);
      try {
        const res = await fetch("/api/manual/metadata", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            source_url: sourceUrl,
            caption: captionText,
            destination_ids: [channel.destination_id],
            metadata_mode: "same",
          }),
        });

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.error || "Tạo metadata thất bại");
        }

        const data: ManualMetadataResult = await res.json();
        const meta = data.same || (data.by_destination && data.by_destination[channel.destination_id]);
        if (meta) {
          setTitle(meta.title);
          setDescription(meta.description);
          setHashtags(meta.hashtags.join(" "));
          setCoreHashtags(meta.core_hashtags ?? []);
          setDynamicHashtags(meta.dynamic_hashtags ?? []);
          const level = (meta as { match_level?: string }).match_level ?? (meta.content_match === false ? "mismatch" : "match");
          if (level === "mismatch") {
            setContentMatchNotice({ match: false, level: "mismatch", reason: meta.content_match_reason || "Video không khớp với niche của kênh này — vẫn đăng được, bạn kiểm tra lại nhé" });
          } else if (level === "borderline") {
            setContentMatchNotice({ match: true, level: "borderline", reason: meta.content_match_reason || "Nội dung liên quan một phần — vẫn đăng bình thường" });
          } else if (meta.content_match === true || (meta as { match_level?: string }).match_level === "match") {
            setContentMatchNotice({ match: true, level: "match", reason: meta.content_match_reason || "Khớp tiêu chí nội dung của kênh" });
          }
        }
      } catch (err: unknown) {
        setMetadataError(err instanceof Error ? err.message : "Tạo metadata AI thất bại");
      } finally {
        setGeneratingMetadata(false);
      }
    },
    [channel.destination_id],
  );

  // Handle URL resolve
  const handleResolve = async () => {
    const raw = input.trim();
    if (!raw || resolving) return;

    setResolving(true);
    setResolveError(null);
    setProfileDetected(null);
    setResolvedVideo(null);
    setContentMatchNotice(null);

    try {
      const res = await fetch("/api/manual/resolve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ input: raw }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || "Không thể nhận diện video");
      }

      if (data.type === "profile") {
        setProfileDetected(data);
        return;
      }

      setResolvedVideo(data);

      const initialCaption = data.caption || "";
      setTitle(initialCaption.slice(0, 80));
      setDescription(initialCaption);
      setHashtags("#shorts #video");

      if (generateAi) {
        triggerAiMetadata(data.source_url, initialCaption);
      }
    } catch (err: unknown) {
      setResolveError(err instanceof Error ? err.message : "Không nhận diện được link");
    } finally {
      setResolving(false);
    }
  };

  // Publish Now to this channel
  const handlePublish = async (forceDuplicate = false) => {
    if (!resolvedVideo || publishing) return;

    setPublishing(true);
    setPublishError(null);
    setDuplicateWarning(null);

    try {
      const fullDesc = `${description}\n\n${hashtags}`.trim();

      const effPrivacy = publishMode === "immediate" ? "public" : publishMode === "scheduled" ? "private" : publishMode;
      const payload: ManualPublishPayload = {
        source_url: resolvedVideo.source_url,
        source_title: resolvedVideo.caption || resolvedVideo.video_id || "Douyin Video",
        video_id: resolvedVideo.video_id,
        thumbnail: resolvedVideo.thumbnail,
        duration: resolvedVideo.duration,
        destination_ids: [channel.destination_id],
        metadata_mode: "same",
        title: title || resolvedVideo.caption || "",
        description: fullDesc,
        privacy_status: effPrivacy as "public" | "unlisted" | "private",
        force_duplicate: forceDuplicate,
        youtube_publish_mode: publishMode,
        youtube_publish_date: publishMode === "scheduled" && schedDate ? schedDate : undefined,
        youtube_publish_time: publishMode === "scheduled" && schedTime ? schedTime : undefined,
        youtube_schedule_timezone: schedTz,
      };

      const res = await fetch(`/api/channels/${channel.destination_id}/publish`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      // Defensive parse: the server must return JSON, but if it ever returns
      // HTML/text (404 page, proxy outage), Safari throws the cryptic
      // "The string did not match the expected pattern." — surface a real
      // HTTP error instead.
      let data: {
        accepted?: boolean;
        code?: string;
        message?: string;
        external_url?: string;
        error?: string;
        detail?: string;
        publications?: ManualPublishResponse["publications"];
      } = {};
      try {
        data = await res.json();
      } catch {
        throw new Error(
          `Publish thất bại (HTTP ${res.status}). Server không trả JSON — thử lại.`,
        );
      }

      if (res.status === 409 && data.code === "DUPLICATE_VIDEO") {
        setDuplicateWarning({
          message: data.message || "Video này đã được đăng lên kênh.",
          external_url: data.external_url,
        });
        return;
      }

      if (!res.ok) {
        throw new Error(data.error || data.detail || "Đăng video thất bại");
      }

      const result = data as ManualPublishResponse;
      if (result.publications && result.publications.length > 0) {
        setActivePublications((prev) => [...result.publications, ...prev]);
        reloadDetail();
      }
    } catch (err: unknown) {
      setPublishError(err instanceof Error ? err.message : "Đăng video thất bại");
    } finally {
      setPublishing(false);
    }
  };

  // Polling for active publications in manual tab
  const pollActiveRef = useRef<NodeJS.Timeout | null>(null);
  useEffect(() => {
    const hasPending = activePublications.some(
      (p) => !["published", "failed"].includes(p.status),
    );
    if (!hasPending) {
      if (pollActiveRef.current) clearInterval(pollActiveRef.current);
      return;
    }

    pollActiveRef.current = setInterval(async () => {
      try {
        const updated = await Promise.all(
          activePublications.map(async (pub) => {
            if (["published", "failed"].includes(pub.status)) return pub;
            const res = await fetch(`/api/manual/publications/${pub.id}`);
            if (!res.ok) return pub;
            return (await res.json()) as ManualPublicationItem;
          }),
        );
        setActivePublications(updated);
        const stillPending = updated.some(
          (p) => !["published", "failed"].includes(p.status),
        );
        if (!stillPending) {
          reloadDetail();
        }
      } catch (e) {
        console.error("Poll error:", e);
      }
    }, 2000);

    return () => {
      if (pollActiveRef.current) clearInterval(pollActiveRef.current);
    };
  }, [activePublications, reloadDetail]);

  // Retry publication
  const handleRetryPub = async (pubId: string) => {
    try {
      const res = await fetch(`/api/manual/publications/${pubId}/retry`, {
        method: "POST",
      });
      if (!res.ok) throw new Error("Thử lại thất bại");
      const updated: ManualPublicationItem = await res.json();
      setActivePublications((prev) => [
        updated,
        ...prev.filter((p) => p.id !== pubId),
      ]);
      reloadDetail();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Thử lại thất bại");
    }
  };

  // Reconnect Google OAuth
  const handleReconnect = () => {
    startTransition(async () => {
      const res = await actionGetOauthUrl(channel.destination_id);
      if (!res.ok) {
        alert(res.error || "Không lấy được link kết nối Google");
        return;
      }
      if (res.url) {
        window.location.assign(res.url);
      }
    });
  };

  // Toggle Auto mode
  const handleToggleEnabled = () => {
    startTransition(async () => {
      const res = await actionToggleDestination(channel.pipeline_id, channel.destination_id, !channel.enabled);
      if (res.ok) {
        reloadDetail();
      } else {
        alert(res.error || "Thao tác thất bại");
      }
    });
  };

  // ==========================================
  // TAB: SOURCES STATE & ACTIONS (AUTO mode)
  // ==========================================
  const [sourceName, setSourceName] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [sourcePlatform, setSourcePlatform] = useState<"douyin" | "facebook">("douyin");
  const [sourceScanInterval, setSourceScanInterval] = useState("15");
  const [sourceMaxPerDay, setSourceMaxPerDay] = useState("5");
  const [sourceStartMode, setSourceStartMode] = useState<"new_only" | "last_n">("new_only");
  const [sourceInitialLimit, setSourceInitialLimit] = useState("10");
  const [sourceIncludeKw, setSourceIncludeKw] = useState("");
  const [sourceExcludeKw, setSourceExcludeKw] = useState("");
  const [addingSource, setAddingSource] = useState(false);
  const [sourceError, setSourceError] = useState<string | null>(null);
  const [syncingSourceId, setSyncingSourceId] = useState<string | null>(null);
  const [deletingSourceId, setDeletingSourceId] = useState<string | null>(null);
  const [workspaceSources, setWorkspaceSources] = useState<WorkspaceSourceItem[]>([]);
  const [importingSourceId, setImportingSourceId] = useState<string | null>(null);
  const [quota, setQuota] = useState<DouyinQuotaStatus | null>(null);
  const [autoStatus, setAutoStatus] = useState<ChannelAutoStatus | null>(null);
  const [autoStatusLoading, setAutoStatusLoading] = useState(false);
  const [globalAccounts, setGlobalAccounts] = useState<{ platform: string; status: string; connected: boolean; used_by_sources?: number; last_verified_at?: string | null }[]>([]);

  const splitKw = (v: string) => v.split(/[\n,]+/).map((s) => s.trim()).filter(Boolean);

  const fetchWorkspaceSources = useCallback(async () => {
    try {
      const res = await fetch(`/api/channels/${channel.destination_id}/sources`);
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data)) setWorkspaceSources(data);
      }
    } catch (e) {
      console.error("Failed to load workspace sources:", e);
    }
  }, [channel.destination_id]);

  const fetchQuota = useCallback(async () => {
    try {
      const res = await fetch(`/api/douyin/quota`);
      if (res.ok) setQuota(await res.json());
    } catch (e) {
      console.error("Failed to load RapidAPI quota:", e);
    }
  }, []);

  const fetchGlobalAccounts = useCallback(async () => {
    try {
      const res = await fetch(`/api/platform-accounts`);
      if (res.ok) setGlobalAccounts(await res.json());
    } catch {}
  }, []);

  const fetchAutoStatus = useCallback(async () => {
    setAutoStatusLoading(true);
    try {
      const res = await fetch(`/api/channels/${channel.destination_id}/auto/status`);
      if (res.ok) setAutoStatus(await res.json());
    } catch (e) {
      console.error("Failed to load auto status:", e);
    } finally {
      setAutoStatusLoading(false);
    }
  }, [channel.destination_id]);

  useEffect(() => {
    fetchWorkspaceSources();
    fetchGlobalAccounts();
    fetchQuota();
  }, [fetchWorkspaceSources, fetchGlobalAccounts, fetchQuota]);

  useEffect(() => {
    if (activeTab === "auto") fetchAutoStatus();
  }, [activeTab, fetchAutoStatus]);

  const handleAddSource = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!sourceName.trim() || !sourceUrl.trim() || addingSource) return;
    setAddingSource(true);
    setSourceError(null);
    try {
      const res = await fetch(`/api/channels/${channel.destination_id}/sources`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          platform: sourcePlatform,
          name: sourceName.trim(),
          url: sourceUrl.trim(),
          scan_interval_minutes: Number(sourceScanInterval) || 15,
          max_videos_per_day: Number(sourceMaxPerDay) || 0,
          start_mode: sourceStartMode,
          initial_limit: Number(sourceInitialLimit) || 10,
          include_keywords: splitKw(sourceIncludeKw),
          exclude_keywords: splitKw(sourceExcludeKw),
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || data.error || "Thêm tác giả thất bại");
      setSourceName("");
      setSourceUrl("");
      reloadDetail();
      fetchWorkspaceSources();
    } catch (err: unknown) {
      setSourceError(err instanceof Error ? err.message : "Thêm tác giả thất bại");
    } finally {
      setAddingSource(false);
    }
  };

  const handleSyncSource = async (sourceId: string) => {
    setSyncingSourceId(sourceId);
    try {
      // Manual-inventory mode: refresh = page 1 newest-first, stop at the
      // first known aweme_id. One RapidAPI request when nothing is new.
      const res = await fetch(`/api/sources/${sourceId}/refresh`, { method: "POST" });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || err.error || "Cập nhật thất bại");
      }
      reloadDetail();
      fetchWorkspaceSources();
      fetchQuota();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Cập nhật thất bại");
    } finally {
      setSyncingSourceId(null);
    }
  };

  // Admin-driven initial backlog import (resumable on quota stop).
  const handleInitialImport = async (sourceId: string, resume = false) => {
    setImportingSourceId(sourceId);
    try {
      const url = resume
        ? `/api/sources/${sourceId}/initial-import/resume`
        : `/api/sources/${sourceId}/initial-import`;
      const res = await fetch(url, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || data.error || "Import thất bại");
      }
      reloadDetail();
      fetchWorkspaceSources();
      fetchQuota();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Import thất bại");
    } finally {
      setImportingSourceId(null);
    }
  };

  const handlePauseSource = async (sourceId: string, enabled: boolean) => {
    const endpoint = enabled ? "pause" : "resume";
    try {
      const res = await fetch(`/api/sources/${sourceId}/${endpoint}`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || data.error || "Thao tác thất bại");
      fetchWorkspaceSources();
      reloadDetail();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Thao tác thất bại");
    }
  };

  // Global PlatformAccount cookie handlers (shared login)
  const [globalCookieDraft, setGlobalCookieDraft] = useState("");
  const [globalCookieBusy, setGlobalCookieBusy] = useState(false);
  const [globalCookieMsg, setGlobalCookieMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [showGlobalCookieEditor, setShowGlobalCookieEditor] = useState(false);

  const handleSaveGlobalCookie = async () => {
    if (!globalCookieDraft.trim() || globalCookieBusy) return;
    setGlobalCookieBusy(true);
    setGlobalCookieMsg(null);
    try {
      const res = await fetch(`/api/platform-accounts/douyin`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cookie: globalCookieDraft }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || data.error || "Lưu cookie thất bại");
      setGlobalCookieMsg({ ok: true, text: "Đã lưu Douyin cookie toàn hệ thống." });
      setShowGlobalCookieEditor(false);
      setGlobalCookieDraft("");
      fetchGlobalAccounts();
    } catch (err: unknown) {
      setGlobalCookieMsg({ ok: false, text: err instanceof Error ? err.message : "Lưu cookie thất bại" });
    } finally {
      setGlobalCookieBusy(false);
    }
  };

  const handleTestGlobalCookie = async () => {
    setGlobalCookieBusy(true);
    setGlobalCookieMsg(null);
    try {
      const res = await fetch(`/api/platform-accounts/douyin/test`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || data.error || "Cookie không hợp lệ");
      setGlobalCookieMsg({ ok: true, text: `Douyin Connected ✅ · ${data.videos_probed ?? ""} videos probed` });
      fetchGlobalAccounts();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Test thất bại";
      setGlobalCookieMsg({ ok: false, text: msg.includes("COOKIE_EXPIRED") ? "Douyin cookie hết hạn — cập nhật lại." : msg });
    } finally {
      setGlobalCookieBusy(false);
    }
  };

  const handleDeleteGlobalCookie = async () => {
    if (!confirm("Xóa Douyin PlatformAccount? Tất cả Douyin sources sẽ tạm pause.")) return;
    setGlobalCookieBusy(true);
    setGlobalCookieMsg(null);
    try {
      const res = await fetch(`/api/platform-accounts/douyin`, { method: "DELETE" });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Xóa thất bại");
      }
      setGlobalCookieMsg({ ok: true, text: "Đã xóa Douyin account." });
      fetchGlobalAccounts();
    } catch (err: unknown) {
      setGlobalCookieMsg({ ok: false, text: err instanceof Error ? err.message : "Xóa thất bại" });
    } finally {
      setGlobalCookieBusy(false);
    }
  };

  const handleDeleteSource = async (sourceId: string) => {
    if (!confirm("Bạn có chắc chắn muốn xóa tác giả này khỏi workspace?")) return;
    setDeletingSourceId(sourceId);
    try {
      const res = await fetch(`/api/channels/${channel.destination_id}/sources/${sourceId}`, {
        method: "DELETE",
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Xóa thất bại");
      }
      reloadDetail();
      fetchWorkspaceSources();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Xóa thất bại");
    } finally {
      setDeletingSourceId(null);
    }
  };

  // ==========================================
  // TAB: INVENTORY FILTER & QUICK PUBLISH
  // ==========================================
  const [inventoryFilter, setInventoryFilter] = useState<string>("all");
  const filteredInventory = (detail.inventory || []).filter((v) => {
    if (inventoryFilter === "all") return true;
    return v.status === inventoryFilter;
  });

  const handleQuickPublishInventory = (video: ChannelInventoryItem) => {
    setInput(video.url);
    setActiveTab("manual");
  };

  // ==========================================
  // TAB: AUTO SETTINGS STATE
  // ==========================================
  const [autoSlots, setAutoSlots] = useState(
    ((detail as unknown as { upload_slots?: string[] }).upload_slots || detail.pipeline?.upload_slots || ["09:00", "12:00", "18:00", "21:00"]).join(", ")
  );
  const [autoLimit, setAutoLimit] = useState(detail.daily_upload_limit || 4);
  const [autoTimezone, setAutoTimezone] = useState(detail.timezone || "Asia/Ho_Chi_Minh");
  const [autoPublishMode, setAutoPublishMode] = useState<"immediate" | "scheduled" | "private" | "unlisted">(
    ((detail as unknown as { youtube_default_publish_mode?: string }).youtube_default_publish_mode as "immediate" | "scheduled" | "private" | "unlisted") || "immediate",
  );
  const [savingAuto, setSavingAuto] = useState(false);
  const [autoSuccess, setAutoSuccess] = useState(false);

  const handleSaveAuto = async (e: React.FormEvent) => {
    e.preventDefault();
    setSavingAuto(true);
    setAutoSuccess(false);
    try {
      const slotList = autoSlots
        .split(/[\s,]+/)
        .map((s) => s.trim())
        .filter(Boolean);
      const res = await fetch(`/api/channels/${channel.destination_id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          daily_upload_limit: Number(autoLimit),
          upload_slots: slotList,
          timezone: autoTimezone,
          youtube_default_publish_mode: autoPublishMode,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Lưu cấu hình thất bại");
      }
      setAutoSuccess(true);
      setTimeout(() => setAutoSuccess(false), 4000);
      reloadDetail();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Lỗi lưu cấu hình Auto");
    } finally {
      setSavingAuto(false);
    }
  };

  // ==========================================
  // TAB: AI PROFILE STATE & ACTIONS
  // ==========================================
  const [aiNiche, setAiNiche] = useState(detail.metadata_profile || "");
  const [aiLanguage, setAiLanguage] = useState(detail.metadata_language || "en");
  const [aiFixedTags, setAiFixedTags] = useState(
    Array.isArray(detail.fixed_hashtags)
      ? detail.fixed_hashtags.join(" ")
      : detail.fixed_hashtags || ""
  );
  const [aiAdaptiveTags, setAiAdaptiveTags] = useState(
    Array.isArray(detail.adaptive_hashtags)
      ? detail.adaptive_hashtags.join(" ")
      : ""
  );
  const [aiPrompt, setAiPrompt] = useState(detail.prompt_override || "");
  const [savingAi, setSavingAi] = useState(false);
  const [aiSuccess, setAiSuccess] = useState(false);

  const handleSaveAiProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    setSavingAi(true);
    setAiSuccess(false);
    try {
      const fixedList = aiFixedTags
        .split(/[\s,]+/)
        .filter((t) => t.trim().startsWith("#"));
      const adaptiveList = aiAdaptiveTags
        .split(/[\s,]+/)
        .filter((t) => t.trim().startsWith("#"));

      const res = await fetch(`/api/channels/${channel.destination_id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          metadata_profile: aiNiche,
          metadata_language: aiLanguage,
          fixed_hashtags: fixedList,
          adaptive_hashtags: adaptiveList,
          prompt_override: aiPrompt,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Lưu AI Profile thất bại");
      }
      setAiSuccess(true);
      setTimeout(() => setAiSuccess(false), 4000);
      reloadDetail();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Lỗi lưu AI profile");
    } finally {
      setSavingAi(false);
    }
  };

  // ==========================================
  // TAB: COMMENTS (AI Comment Reply — a SEPARATE subsystem)
  // Nothing here reads or writes the metadata prompt (prompt_override).
  // ==========================================
  const [comments, setComments] = useState<YouTubeComment[]>([]);
  const [commentMeta, setCommentMeta] = useState<CommentListResponse | null>(null);
  const [commentsLoading, setCommentsLoading] = useState(false);
  const [scanningComments, setScanningComments] = useState(false);
  const [commentFilter, setCommentFilter] = useState<string>("");
  const [busyCommentId, setBusyCommentId] = useState<string | null>(null);
  const [editingCommentId, setEditingCommentId] = useState<string | null>(null);
  const [editReplyText, setEditReplyText] = useState("");
  const [commentNotice, setCommentNotice] = useState<string | null>(null);

  // AI Comment Reply settings (independent from aiPrompt / prompt_override).
  const [crEnabled, setCrEnabled] = useState<boolean>(detail.comment_reply_enabled ?? false);
  const [crMode, setCrMode] = useState<CommentReplyMode>(
    (detail.comment_reply_mode as CommentReplyMode) || "off",
  );
  const [crPrompt, setCrPrompt] = useState(detail.comment_reply_system_prompt || "");
  const [crLanguage, setCrLanguage] = useState(detail.comment_reply_language || "auto");
  const [crStyle, setCrStyle] = useState(detail.comment_reply_style || "friendly");
  const [crDailyLimit, setCrDailyLimit] = useState(detail.comment_reply_daily_limit ?? 20);
  const [crMinInterval, setCrMinInterval] = useState(
    detail.comment_reply_min_interval_seconds ?? 180,
  );
  const [crNewOnly, setCrNewOnly] = useState(detail.comment_reply_new_only ?? true);
  const [crPositive, setCrPositive] = useState(detail.comment_reply_to_positive ?? true);
  const [crQuestions, setCrQuestions] = useState(detail.comment_reply_to_questions ?? true);
  const [crNeutral, setCrNeutral] = useState(detail.comment_reply_to_neutral ?? false);
  const [crNegative, setCrNegative] = useState(detail.comment_reply_to_negative ?? false);
  const [crEmojiOnly, setCrEmojiOnly] = useState(detail.comment_reply_to_emoji_only ?? false);
  // The default prompt the backend uses when the field below is empty.
  const [crDefaultPrompt, setCrDefaultPrompt] = useState("");
  const [crFunny, setCrFunny] = useState(detail.comment_reply_to_funny ?? false);
  const [crExcited, setCrExcited] = useState(detail.comment_reply_to_excited ?? false);
  const [savingComment, setSavingComment] = useState(false);
  const [commentSettingsSuccess, setCommentSettingsSuccess] = useState(false);

  const fetchCommentSettings = useCallback(async () => {
    try {
      const res = await fetch(
        `/api/channels/${channel.destination_id}/comment-reply-settings`,
      );
      if (!res.ok) return;
      const data = await res.json();
      setCrEnabled(Boolean(data.enabled));
      setCrMode((data.mode as CommentReplyMode) || "off");
      setCrPrompt(data.system_prompt || "");
      setCrDefaultPrompt(data.default_system_prompt || "");
      setCrLanguage(data.language || "auto");
      setCrStyle(data.style || "friendly");
      setCrDailyLimit(data.daily_limit ?? 20);
      setCrMinInterval(data.min_interval_seconds ?? 180);
      setCrNewOnly(Boolean(data.new_only));
      setCrPositive(Boolean(data.reply_to_positive));
      setCrQuestions(Boolean(data.reply_to_questions));
      setCrNeutral(Boolean(data.reply_to_neutral));
      setCrNegative(Boolean(data.reply_to_negative));
      setCrEmojiOnly(Boolean(data.reply_to_emoji_only));
      setCrFunny(Boolean(data.reply_to_funny));
      setCrExcited(Boolean(data.reply_to_excited));
    } catch (e) {
      console.error("Failed to load comment reply settings:", e);
    }
  }, [channel.destination_id]);

  const fetchComments = useCallback(
    async (status?: string): Promise<CommentListResponse | null> => {
      setCommentsLoading(true);
      try {
        const qs = status ? `?status=${encodeURIComponent(status)}` : "";
        const res = await fetch(`/api/channels/${channel.destination_id}/comments${qs}`);
        if (!res.ok) return null;
        const data: CommentListResponse = await res.json();
        setComments(Array.isArray(data.items) ? data.items : []);
        setCommentMeta(data);
        return data;
      } catch (e) {
        console.error("Failed to load comments:", e);
        return null;
      } finally {
        setCommentsLoading(false);
      }
    },
    [channel.destination_id],
  );

  useEffect(() => {
    if (activeTab !== "comments") return;
    fetchComments(commentFilter);
    fetchCommentSettings();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab]);

  const notifyComments = (msg: string) => {
    setCommentNotice(msg);
    setTimeout(() => setCommentNotice(null), 4000);
  };

  const handleSaveCommentSettings = async (e?: React.FormEvent) => {
    e?.preventDefault();
    setSavingComment(true);
    setCommentSettingsSuccess(false);
    try {
      const res = await fetch(
        `/api/channels/${channel.destination_id}/comment-reply-settings`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            enabled: crEnabled,
            mode: crMode,
            system_prompt: crPrompt,
            language: crLanguage,
            style: crStyle,
            daily_limit: crDailyLimit,
            min_interval_seconds: crMinInterval,
            new_only: crNewOnly,
            reply_to_positive: crPositive,
            reply_to_questions: crQuestions,
            reply_to_neutral: crNeutral,
            reply_to_negative: crNegative,
            reply_to_emoji_only: crEmojiOnly,
            reply_to_funny: crFunny,
            reply_to_excited: crExcited,
          }),
        },
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Lưu cài đặt comment thất bại");
      }
      setCommentSettingsSuccess(true);
      setTimeout(() => setCommentSettingsSuccess(false), 4000);
      reloadDetail();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Lỗi lưu cài đặt AI Comment Reply");
    } finally {
      setSavingComment(false);
    }
  };

  const handleScanComments = async () => {
    setScanningComments(true);
    try {
      const res = await fetch(
        `/api/channels/${channel.destination_id}/comments/scan`,
        { method: "POST" },
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Quét bình luận thất bại");
      }

      const before = commentMeta?.total ?? comments.length;
      notifyComments("Đang quét bình luận trên YouTube…");

      // The scan runs in the background, so poll a few times and report the
      // real outcome instead of claiming success unconditionally.
      for (const delay of [2500, 6000, 12000]) {
        await new Promise((resolve) => setTimeout(resolve, delay));
        const data = await fetchComments(commentFilter);
        if (data && data.total > before) {
          notifyComments(`Đã lấy thêm ${data.total - before} bình luận.`);
          return;
        }
      }
      notifyComments("Đã quét xong — chưa thấy bình luận mới.");
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Quét thất bại");
    } finally {
      setScanningComments(false);
    }
  };

  const handleGenerateComment = async (commentId: string) => {
    setBusyCommentId(commentId);
    try {
      const res = await fetch(
        `/api/channels/${channel.destination_id}/comments/${commentId}/generate-reply`,
        { method: "POST" },
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Tạo reply thất bại");
      if (data.error) notifyComments(`AI: ${data.error}`);
      await fetchComments(commentFilter);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Tạo reply thất bại");
    } finally {
      setBusyCommentId(null);
    }
  };

  const handleSendCommentReply = async (commentId: string, text: string) => {
    setBusyCommentId(commentId);
    try {
      const res = await fetch(
        `/api/channels/${channel.destination_id}/comments/${commentId}/reply`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text }),
        },
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Gửi reply thất bại");
      if (!data.ok) {
        throw new Error(data.error || "Gửi reply thất bại");
      }
      setEditingCommentId(null);
      setEditReplyText("");
      notifyComments("Đã trả lời bình luận trên YouTube.");
      await fetchComments(commentFilter);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Gửi reply thất bại");
    } finally {
      setBusyCommentId(null);
    }
  };

  const handleSkipComment = async (commentId: string) => {
    setBusyCommentId(commentId);
    try {
      const res = await fetch(
        `/api/channels/${channel.destination_id}/comments/${commentId}/skip`,
        { method: "POST" },
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Bỏ qua thất bại");
      }
      notifyComments("Đã bỏ qua bình luận này.");
      await fetchComments(commentFilter);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Bỏ qua thất bại");
    } finally {
      setBusyCommentId(null);
    }
  };

  const commentStatusTone = (status: string): string => {
    switch (status) {
      case "replied":
        return "bg-emerald-50 text-emerald-700 border-emerald-200";
      case "ready_to_reply":
        return "bg-indigo-50 text-indigo-700 border-indigo-200";
      case "held":
        return "bg-amber-50 text-amber-700 border-amber-200";
      case "failed":
        return "bg-rose-50 text-rose-700 border-rose-200";
      case "ignored":
      case "skipped":
        return "bg-slate-100 text-slate-600 border-slate-200";
      default:
        return "bg-sky-50 text-sky-700 border-sky-200";
    }
  };

  // ==========================================
  // TAB: SETTINGS FORM STATE & ACTIONS
  // ==========================================
  const [settingsName, setSettingsName] = useState(channel.channel_title || "");
  const [settingsLimit, setSettingsLimit] = useState(detail.daily_upload_limit || 4);
  const [settingsPrivacy, setSettingsPrivacy] = useState(detail.pipeline?.default_privacy || "public");
  const [settingsTz, setSettingsTz] = useState(detail.timezone || "Asia/Ho_Chi_Minh");
  const [settingsPublishMode, setSettingsPublishMode] = useState(
    ((detail as unknown as { youtube_default_publish_mode?: string }).youtube_default_publish_mode as string) || "immediate",
  );
  const [savingSettings, setSavingSettings] = useState(false);
  const [settingsSuccess, setSettingsSuccess] = useState(false);

  const handleSaveSettings = async (e: React.FormEvent) => {
    e.preventDefault();
    setSavingSettings(true);
    setSettingsSuccess(false);

    try {
      const res = await fetch(`/api/channels/${channel.destination_id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: settingsName,
          prompt_override: aiPrompt,
          daily_upload_limit: Number(settingsLimit),
          default_privacy: settingsPrivacy,
          timezone: settingsTz,
          youtube_default_publish_mode: settingsPublishMode,
        }),
      });
      if (res.ok) {
        setSettingsSuccess(true);
        setTimeout(() => setSettingsSuccess(false), 4000);
        reloadDetail();
      } else {
        const err = await res.json().catch(() => ({}));
        alert(err.detail || "Lưu cài đặt thất bại");
      }
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Lỗi lưu cài đặt");
    } finally {
      setSavingSettings(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Back button */}
      <Link
        href="/channels"
        className="inline-flex min-h-[44px] items-center gap-1.5 rounded-lg px-2 py-1 text-sm font-semibold text-slate-500 transition hover:bg-slate-200/60 hover:text-slate-800"
      >
        <IconBack size={16} />
        Channels
      </Link>

      {/* ============================================================ */}
      {/* WORKSPACE IDENTITY HEADER (Requirement 18)                   */}
      {/* ============================================================ */}
      <div className="rounded-2xl border border-indigo-200/80 bg-gradient-to-r from-indigo-50/70 via-white to-slate-50 p-5 shadow-sm">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-4">
            <div className="relative h-16 w-16 shrink-0 overflow-hidden rounded-2xl bg-slate-900 ring-2 ring-indigo-500/30 shadow-md">
              {channel.avatar_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={channel.avatar_url}
                  alt={channel.channel_title}
                  className="h-full w-full object-cover"
                />
              ) : (
                <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-rose-500 to-red-600 text-2xl font-black text-white">
                  {(channel.channel_title || "Y")[0].toUpperCase()}
                </div>
              )}
              <span className="absolute bottom-0 right-0 flex h-5 w-5 items-center justify-center rounded-tl-lg bg-red-600 text-[9px] font-black text-white">
                YT
              </span>
            </div>

            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[11px] font-extrabold uppercase tracking-wider text-indigo-600">
                  Channel Workspace
                </span>
                {isConnected ? (
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-bold text-emerald-700 ring-1 ring-emerald-600/20">
                    <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
                    Connected
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-rose-50 px-2.5 py-0.5 text-xs font-bold text-rose-700 ring-1 ring-rose-600/20">
                    <span className="h-2 w-2 rounded-full bg-rose-500" />
                    Not Connected
                  </span>
                )}
                {channel.enabled ? (
                  <span className="inline-flex items-center rounded-full bg-indigo-50 px-2.5 py-0.5 text-xs font-bold text-indigo-700 ring-1 ring-indigo-600/20">
                    Auto ON
                  </span>
                ) : (
                  <span className="inline-flex items-center rounded-full bg-amber-50 px-2.5 py-0.5 text-xs font-bold text-amber-700 ring-1 ring-amber-600/20">
                    Auto OFF
                  </span>
                )}
              </div>

              <div className="mt-1">
                <span className="text-xs font-medium text-slate-400">Channel: </span>
                <span className="text-xl font-black text-slate-900 leading-tight">
                  {channel.channel_title}
                </span>
              </div>

              <div className="mt-0.5 text-xs text-slate-500 flex flex-wrap items-center gap-2">
                <span>
                  Workspace: <strong className="text-slate-800 font-bold">{channel.pipeline_name || channel.channel_title}</strong>
                </span>
                {channel.channel_id && (
                  <span className="text-slate-400">· ID: <code className="font-mono text-slate-600">{channel.channel_id}</code></span>
                )}
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {channel.channel_id && (
              <a
                href={`https://www.youtube.com/channel/${channel.channel_id}`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex min-h-[44px] items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-bold text-slate-700 shadow-sm hover:bg-slate-50 transition"
              >
                Open on YouTube ↗
              </a>
            )}

            <button
              type="button"
              onClick={handleReconnect}
              disabled={pending}
              className="inline-flex min-h-[44px] items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-bold text-slate-700 shadow-sm hover:bg-slate-50 transition disabled:opacity-50"
            >
              {pending ? "…" : isConnected ? "Reconnect OAuth" : "Connect OAuth"}
            </button>

            <button
              type="button"
              onClick={handleToggleEnabled}
              disabled={pending}
              className={`inline-flex min-h-[44px] items-center rounded-xl px-4 py-2 text-xs font-bold transition ${
                channel.enabled
                  ? "bg-slate-100 text-slate-700 hover:bg-slate-200"
                  : "bg-emerald-600 text-white hover:bg-emerald-500 shadow-sm"
              }`}
            >
              {channel.enabled ? "Pause Auto" : "Resume Auto"}
            </button>
          </div>
        </div>
      </div>

      {/* ============================================================ */}
      {/* TABS NAVIGATION (Requirement 3: 9 Isolated Tabs)             */}
      {/* ============================================================ */}
      <div className="flex items-center gap-1 border-b border-slate-200 overflow-x-auto pb-1 scrollbar-thin">
        <button
          type="button"
          onClick={() => setActiveTab("overview")}
          className={`flex min-h-[44px] items-center gap-1.5 border-b-2 px-3.5 py-2 text-xs font-extrabold transition whitespace-nowrap ${
            activeTab === "overview"
              ? "border-indigo-600 text-indigo-700"
              : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800"
          }`}
        >
          <IconDashboard size={15} />
          Overview
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("manual")}
          className={`flex min-h-[44px] items-center gap-1.5 border-b-2 px-3.5 py-2 text-xs font-extrabold transition whitespace-nowrap ${
            activeTab === "manual"
              ? "border-indigo-600 text-indigo-700"
              : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800"
          }`}
        >
          <IconUpload size={15} />
          Manual
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("auto")}
          className={`flex min-h-[44px] items-center gap-1.5 border-b-2 px-3.5 py-2 text-xs font-extrabold transition whitespace-nowrap ${
            activeTab === "auto"
              ? "border-indigo-600 text-indigo-700"
              : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800"
          }`}
        >
          <IconClock size={15} />
          Auto
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("sources")}
          className={`flex min-h-[44px] items-center gap-1.5 border-b-2 px-3.5 py-2 text-xs font-extrabold transition whitespace-nowrap ${
            activeTab === "sources"
              ? "border-indigo-600 text-indigo-700"
              : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800"
          }`}
        >
          <IconSources size={15} />
          Sources
          <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-black text-slate-600">
            {detail.sources?.length || 0}
          </span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("inventory")}
          className={`flex min-h-[44px] items-center gap-1.5 border-b-2 px-3.5 py-2 text-xs font-extrabold transition whitespace-nowrap ${
            activeTab === "inventory"
              ? "border-indigo-600 text-indigo-700"
              : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800"
          }`}
        >
          <IconInventory size={15} />
          Inventory
          <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-black text-slate-600">
            {detail.inventory_count || detail.inventory?.length || 0}
          </span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("queue")}
          className={`flex min-h-[44px] items-center gap-1.5 border-b-2 px-3.5 py-2 text-xs font-extrabold transition whitespace-nowrap ${
            activeTab === "queue"
              ? "border-indigo-600 text-indigo-700"
              : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800"
          }`}
        >
          <IconClock size={15} />
          Queue
          {detail.queue?.length > 0 ? (
            <span className="rounded-full bg-indigo-100 px-1.5 py-0.5 text-[10px] font-black text-indigo-700">
              {detail.queue.length}
            </span>
          ) : null}
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("upcoming")}
          className={`flex min-h-[44px] items-center gap-1.5 border-b-2 px-3.5 py-2 text-xs font-extrabold transition whitespace-nowrap ${
            activeTab === "upcoming"
              ? "border-indigo-600 text-indigo-700"
              : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800"
          }`}
        >
          <IconClock size={15} />
          Upcoming
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("published")}
          className={`flex min-h-[44px] items-center gap-1.5 border-b-2 px-3.5 py-2 text-xs font-extrabold transition whitespace-nowrap ${
            activeTab === "published"
              ? "border-indigo-600 text-indigo-700"
              : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800"
          }`}
        >
          <IconPublications size={15} />
          Published
          <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-black text-slate-600">
            {detail.published?.length || 0}
          </span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("analytics")}
          className={`flex min-h-[44px] items-center gap-1.5 border-b-2 px-3.5 py-2 text-xs font-extrabold transition whitespace-nowrap ${
            activeTab === "analytics"
              ? "border-indigo-600 text-indigo-700"
              : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800"
          }`}
        >
          <IconDashboard size={15} />
          Analytics
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("research")}
          className={`flex min-h-[44px] items-center gap-1.5 border-b-2 px-3.5 py-2 text-xs font-extrabold transition whitespace-nowrap ${
            activeTab === "research"
              ? "border-indigo-600 text-indigo-700"
              : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800"
          }`}
        >
          <IconSparkles size={15} />
          AI Research
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("dna")}
          className={`flex min-h-[44px] items-center gap-1.5 border-b-2 px-3.5 py-2 text-xs font-extrabold transition whitespace-nowrap ${
            activeTab === "dna"
              ? "border-indigo-600 text-indigo-700"
              : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800"
          }`}
        >
          <IconSparkles size={15} />
          DNA
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("comments")}
          className={`flex min-h-[44px] items-center gap-1.5 border-b-2 px-3.5 py-2 text-xs font-extrabold transition whitespace-nowrap ${
            activeTab === "comments"
              ? "border-indigo-600 text-indigo-700"
              : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800"
          }`}
        >
          <IconSparkles size={15} />
          Comments
          {detail.comment_count ? (
            <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-black text-slate-600">
              {detail.comment_count}
            </span>
          ) : null}
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("ai_profile")}
          className={`flex min-h-[44px] items-center gap-1.5 border-b-2 px-3.5 py-2 text-xs font-extrabold transition whitespace-nowrap ${
            activeTab === "ai_profile"
              ? "border-indigo-600 text-indigo-700"
              : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800"
          }`}
        >
          <IconSparkles size={15} />
          AI Profile
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("settings")}
          className={`flex min-h-[44px] items-center gap-1.5 border-b-2 px-3.5 py-2 text-xs font-extrabold transition whitespace-nowrap ${
            activeTab === "settings"
              ? "border-indigo-600 text-indigo-700"
              : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800"
          }`}
        >
          <IconSettings size={15} />
          Settings
        </button>
      </div>

      {/* ============================================================ */}
      {/* TAB 1: OVERVIEW                                              */}
      {/* ============================================================ */}
      {activeTab === "overview" && (
        <div className="space-y-6">
          {/* Summary Stats */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
            <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <span className="text-[11px] font-bold text-slate-400">Published today</span>
              <p className="mt-1 text-2xl font-black text-slate-900">
                {channel.published_today} <span className="text-xs font-semibold text-slate-400">/ {detail.daily_upload_limit}</span>
              </p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <span className="text-[11px] font-bold text-slate-400">Queue pending</span>
              <p className="mt-1 text-2xl font-black text-slate-900">{channel.queue_count}</p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <span className="text-[11px] font-bold text-slate-400">Inventory</span>
              <p className="mt-1 text-2xl font-black text-slate-900">
                {detail.inventory_count || detail.inventory?.length || 0}
              </p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <span className="text-[11px] font-bold text-slate-400">Failed jobs</span>
              <p className="mt-1 text-2xl font-black text-slate-900">{detail.failed_count || 0}</p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <span className="text-[11px] font-bold text-slate-400">Next upload</span>
              <p className="mt-1 text-base font-black text-indigo-600 truncate">
                {detail.next_slot ? formatTime(detail.next_slot) : "Waiting"}
              </p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <span className="text-[11px] font-bold text-slate-400">Auto Mode</span>
              <p className="mt-1 text-base font-black text-slate-900">
                {channel.enabled ? (
                  <span className="text-emerald-600">ACTIVE</span>
                ) : (
                  <span className="text-amber-600">PAUSED</span>
                )}
              </p>
            </div>
          </div>

          {/* FLOW GRAPH (Requirement 12) */}
          <Card className="p-5 sm:p-6">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-extrabold text-slate-900">Workspace Pipeline Flow</h3>
                <p className="text-xs text-slate-500">
                  Dòng chảy nội dung độc lập của kênh {channel.channel_title}
                </p>
              </div>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-bold text-emerald-700 ring-1 ring-emerald-600/20">
                <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
                Isolated Workspace
              </span>
            </div>

            <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-5">
              <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-3.5">
                <div className="flex items-center justify-between text-xs text-slate-500 font-bold">
                  <span>1. Sources</span>
                  <IconSources size={14} />
                </div>
                <p className="mt-2 text-2xl font-black text-slate-900">{detail.sources?.length || 0}</p>
                <p className="mt-0.5 text-[11px] text-slate-500">Tác giả Douyin</p>
                <button
                  type="button"
                  onClick={() => setActiveTab("sources")}
                  className="mt-3 text-xs font-bold text-indigo-600 hover:underline"
                >
                  Quản lý Sources →
                </button>
              </div>

              <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-3.5">
                <div className="flex items-center justify-between text-xs text-slate-500 font-bold">
                  <span>2. Inventory</span>
                  <IconInventory size={14} />
                </div>
                <p className="mt-2 text-2xl font-black text-slate-900">
                  {detail.inventory_count || detail.inventory?.length || 0}
                </p>
                <p className="mt-0.5 text-[11px] text-slate-500">Video trong kho</p>
                <button
                  type="button"
                  onClick={() => setActiveTab("inventory")}
                  className="mt-3 text-xs font-bold text-indigo-600 hover:underline"
                >
                  Xem kho video →
                </button>
              </div>

              <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-3.5">
                <div className="flex items-center justify-between text-xs text-slate-500 font-bold">
                  <span>3. Scheduler</span>
                  <IconClock size={14} />
                </div>
                <p className="mt-2 text-2xl font-black text-slate-900">{detail.daily_upload_limit} / ngày</p>
                <p className="mt-0.5 text-[11px] text-slate-500">{detail.pipeline?.upload_slots?.length || 0} slots giờ</p>
                <button
                  type="button"
                  onClick={() => setActiveTab("auto")}
                  className="mt-3 text-xs font-bold text-indigo-600 hover:underline"
                >
                  Cài đặt Auto →
                </button>
              </div>

              <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-3.5">
                <div className="flex items-center justify-between text-xs text-slate-500 font-bold">
                  <span>4. AI Profile</span>
                  <IconSparkles size={14} />
                </div>
                <p className="mt-2 text-base font-black text-slate-900 truncate">
                  {detail.metadata_language?.toUpperCase() || "EN"}
                </p>
                <p className="mt-0.5 text-[11px] text-slate-500 truncate">
                  {detail.metadata_profile ? "Custom Profile" : "Default"}
                </p>
                <button
                  type="button"
                  onClick={() => setActiveTab("ai_profile")}
                  className="mt-3 text-xs font-bold text-indigo-600 hover:underline"
                >
                  Chỉnh AI Profile →
                </button>
              </div>

              <div className="rounded-xl border border-indigo-200 bg-indigo-50/60 p-3.5">
                <div className="flex items-center justify-between text-xs text-indigo-600 font-bold">
                  <span>5. YouTube</span>
                  <span className="text-[10px] font-black text-red-600">YT</span>
                </div>
                <p className="mt-2 text-base font-black text-slate-900 truncate">{channel.channel_title}</p>
                <p className="mt-0.5 text-[11px] text-slate-500">{channel.published_today} video đã đăng</p>
                <button
                  type="button"
                  onClick={() => setActiveTab("published")}
                  className="mt-3 text-xs font-bold text-indigo-700 hover:underline"
                >
                  Xem đã đăng →
                </button>
              </div>
            </div>
          </Card>

          {/* Quick Shortcuts */}
          <div className="flex flex-wrap gap-2.5">
            <button
              type="button"
              onClick={() => setActiveTab("manual")}
              className="inline-flex min-h-[44px] items-center gap-1.5 rounded-xl bg-indigo-600 px-4 py-2 text-xs font-bold text-white shadow-sm hover:bg-indigo-500"
            >
              <IconUpload size={15} />
              Đăng video thủ công (Manual Publish)
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("sources")}
              className="inline-flex min-h-[44px] items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-bold text-slate-700 shadow-sm hover:bg-slate-50"
            >
              <IconPlus size={15} />
              Thêm tác giả Douyin
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("inventory")}
              className="inline-flex min-h-[44px] items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-bold text-slate-700 shadow-sm hover:bg-slate-50"
            >
              <IconInventory size={15} />
              Kho video ({detail.inventory_count || detail.inventory?.length || 0})
            </button>
          </div>

          {/* AI Comment Reply: auxiliary worker, NOT part of the publishing pipeline */}
          <Card className="p-5 sm:p-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="text-sm font-extrabold text-slate-900">
                  YouTube Comments → AI Reply → YouTube Replies
                </h3>
                <p className="text-xs text-slate-500">
                  Worker phụ độc lập, không nằm trong pipeline đăng video.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setActiveTab("comments")}
                className="inline-flex min-h-[40px] items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-bold text-slate-700 shadow-sm hover:bg-slate-50"
              >
                AI Reply ({detail.comment_reply_mode || "off"}) →
              </button>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] font-bold">
              <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-slate-600">
                Bình luận: {detail.comment_count || 0}
              </span>
              <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-slate-600">
                Đã trả lời hôm nay: {detail.comment_replies_today || 0} / {detail.comment_reply_daily_limit ?? 20}
              </span>
              <span
                className={`rounded-full border px-3 py-1 ${
                  detail.comment_oauth_ready
                    ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                    : "border-amber-200 bg-amber-50 text-amber-800"
                }`}
              >
                {detail.comment_oauth_ready
                  ? "OAuth comment: OK (force-ssl)"
                  : "Reconnect required for comment replies"}
              </span>
            </div>
          </Card>
        </div>
      )}

      {/* ============================================================ */}
      {/* TAB 2: MANUAL PUBLISH                                        */}
      {/* ============================================================ */}
      {activeTab === "manual" && (
        <div className="space-y-6">
          <Card className="p-5 sm:p-6">
            <div className="flex flex-col gap-2">
              <label htmlFor="douyin-channel-input" className="text-sm font-extrabold text-slate-900">
                Dán link Douyin để đăng ngay lên kênh {channel.channel_title}
              </label>
              <p className="text-xs text-slate-500">
                Workspace: <span className="font-bold text-slate-700">{channel.channel_title}</span>. Video sẽ được xử lý với bộ AI Profile và đăng trực tiếp vào kênh này (không xuất hiện kênh khác).
              </p>

              <div className="mt-2 flex flex-col gap-2.5 sm:flex-row">
                <div className="relative flex-1">
                  <input
                    id="douyin-channel-input"
                    type="text"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        handleResolve();
                      }
                    }}
                    placeholder="Dán link https://v.douyin.com/... hoặc toàn bộ văn bản chia sẻ rồi nhấn Enter"
                    disabled={resolving || publishing}
                    className="w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 disabled:bg-slate-50"
                  />
                  {input && (
                    <button
                      type="button"
                      onClick={() => setInput("")}
                      className="absolute right-3 top-2.5 text-slate-400 hover:text-slate-600"
                    >
                      <IconX size={16} />
                    </button>
                  )}
                </div>

                <button
                  type="button"
                  onClick={handleResolve}
                  disabled={resolving || !input.trim() || publishing}
                  className="inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-xl bg-indigo-600 px-6 py-2.5 text-xs font-bold text-white shadow-sm hover:bg-indigo-500 disabled:opacity-50"
                >
                  {resolving ? "Đang phân tích…" : "Enter"}
                </button>
              </div>

              {resolveError && (
                <p className="mt-1 flex items-center gap-1.5 text-xs font-bold text-rose-600">
                  <IconAlert size={14} />
                  {resolveError}
                </p>
              )}
            </div>

            {/* Profile detection warning */}
            {profileDetected && (
              <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50/70 p-4 text-xs text-amber-800">
                <p className="font-bold">Đã nhận diện link trang cá nhân (Profile URL):</p>
                <p className="mt-1 font-mono text-[11px] break-all">{profileDetected.source_url}</p>
                <p className="mt-2">
                  Manual Publish cần link video cụ thể. Bạn có thể thêm tác giả này vào tab <strong>Sources</strong> để hệ thống tự động cào video.
                </p>
                <button
                  type="button"
                  onClick={() => {
                    setSourceName("Douyin Creator");
                    setSourceUrl(profileDetected.source_url);
                    setActiveTab("sources");
                  }}
                  className="mt-3 inline-flex min-h-[36px] items-center gap-1 rounded-lg bg-amber-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-amber-500"
                >
                  Thêm vào Sources →
                </button>
              </div>
            )}

            {/* Resolved Video Card */}
            {resolvedVideo && (
              <div className="mt-6 rounded-2xl border border-slate-200 bg-slate-50/60 p-4 sm:p-5">
                <div className="flex flex-col gap-4 sm:flex-row">
                  <div className="relative aspect-[9/16] w-28 shrink-0 overflow-hidden rounded-xl bg-slate-900 sm:w-36 shadow-sm">
                    {resolvedVideo.thumbnail ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={resolvedVideo.thumbnail}
                        alt="Thumbnail"
                        className="h-full w-full object-cover"
                      />
                    ) : (
                      <div className="flex h-full w-full items-center justify-center text-xs text-slate-500">
                        No thumbnail
                      </div>
                    )}
                    <span className="absolute bottom-1.5 right-1.5 rounded-md bg-black/75 px-1.5 py-0.5 font-mono text-[10px] font-bold text-white">
                      {formatDuration(resolvedVideo.duration)}
                    </span>
                  </div>

                  <div className="min-w-0 flex-1 space-y-2 text-xs">
                    <div>
                      <span className="font-bold text-slate-400">Original Caption:</span>
                      <p className="mt-0.5 text-sm font-semibold text-slate-800 line-clamp-2">
                        {resolvedVideo.caption || "Không có tiêu đề"}
                      </p>
                    </div>

                    <div className="flex flex-wrap gap-4 text-slate-500">
                      {resolvedVideo.author_name && (
                        <span>Tác giả: <strong className="text-slate-700">{resolvedVideo.author_name}</strong></span>
                      )}
                      <span>ID: <code className="font-mono text-slate-600">{resolvedVideo.video_id}</code></span>
                    </div>

                    {contentMatchNotice && (
                      <div className={`rounded-xl p-3 text-xs font-semibold ${contentMatchNotice.level === "mismatch" ? "border border-rose-200 bg-rose-50 text-rose-800" : contentMatchNotice.level === "borderline" ? "border border-amber-200 bg-amber-50 text-amber-800" : "border border-emerald-200 bg-emerald-50 text-emerald-800"}`}>
                        <span className="font-bold">{contentMatchNotice.level === "mismatch" ? "⛔ AI Content Mismatch (vẫn đăng được): " : contentMatchNotice.level === "borderline" ? "⚠ AI Borderline (vẫn đăng bình thường): " : "✓ AI Content Match: "}</span>
                        {contentMatchNotice.reason}
                      </div>
                    )}
                  </div>
                </div>

                {/* Metadata Editor */}
                <div className="mt-5 space-y-3.5 border-t border-slate-200/80 pt-4">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-extrabold uppercase tracking-wider text-slate-700">
                      YouTube Metadata (Kênh {channel.channel_title})
                    </span>
                    <button
                      type="button"
                      onClick={() => triggerAiMetadata(resolvedVideo.source_url, resolvedVideo.caption || "")}
                      disabled={generatingMetadata}
                      className="inline-flex min-h-[36px] items-center gap-1.5 rounded-lg border border-indigo-200 bg-white px-2.5 py-1 text-xs font-bold text-indigo-600 hover:bg-indigo-50 disabled:opacity-50"
                    >
                      <IconSparkles size={13} />
                      {generatingMetadata ? "Đang tạo lại AI…" : "Generate AI Metadata"}
                    </button>
                  </div>

                  {metadataError && (
                    <p className="text-xs font-semibold text-rose-600">{metadataError}</p>
                  )}

                  <div>
                    <label className="text-xs font-bold text-slate-600">Tiêu đề (Title):</label>
                    <input
                      type="text"
                      value={title}
                      maxLength={100}
                      onChange={(e) => setTitle(e.target.value)}
                      className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none"
                    />
                  </div>

                  <div>
                    <label className="text-xs font-bold text-slate-600">Mô tả (Description):</label>
                    <textarea
                      rows={3}
                      value={description}
                      onChange={(e) => setDescription(e.target.value)}
                      className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-800 shadow-sm focus:border-indigo-500 focus:outline-none"
                    />
                  </div>

                  {(coreHashtags.length > 0 || dynamicHashtags.length > 0) ? (
                    <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
                      <p className="text-[11px] font-extrabold text-slate-600">Hashtag split (Channel DNA)</p>
                      {coreHashtags.length > 0 ? (
                        <div className="mt-1.5">
                          <p className="text-[10px] font-bold text-slate-500">CORE → inherited from channel (locked)</p>
                          <div className="mt-1 flex flex-wrap gap-1">
                            {coreHashtags.map((h) => (
                              <span key={h} className="rounded-full bg-slate-900 px-2 py-0.5 font-mono text-[10px] font-bold text-white">
                                {h} 🔒
                              </span>
                            ))}
                          </div>
                        </div>
                      ) : null}
                      {dynamicHashtags.length > 0 ? (
                        <div className="mt-1.5">
                          <p className="text-[10px] font-bold text-slate-500">DYNAMIC → generated for this video</p>
                          <div className="mt-1 flex flex-wrap gap-1">
                            {dynamicHashtags.map((h) => (
                              <span key={h} className="rounded-full bg-indigo-100 px-2 py-0.5 font-mono text-[10px] font-bold text-indigo-700">
                                {h}
                              </span>
                            ))}
                          </div>
                        </div>
                      ) : null}
                    </div>
                  ) : null}

                  <div>
                    <label className="text-xs font-bold text-slate-600">Hashtags (5 hashtags):</label>
                    <input
                      type="text"
                      value={hashtags}
                      onChange={(e) => setHashtags(e.target.value)}
                      className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 font-mono text-xs font-bold text-indigo-600 shadow-sm focus:border-indigo-500 focus:outline-none"
                    />
                  </div>

                  <div className="mt-1">
                    <YouTubePublishSelector
                      mode={publishMode}
                      onModeChange={(m) => {
                        setPublishMode(m);
                        if (m === "immediate") setPrivacy("public");
                        else if (m === "scheduled") setPrivacy("private");
                        else setPrivacy(m);
                      }}
                      date={schedDate}
                      time={schedTime}
                      timezone={schedTz}
                      onDateChange={setSchedDate}
                      onTimeChange={setSchedTime}
                      onTimezoneChange={setSchedTz}
                    />
                  </div>

                  <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
                    <div className="flex items-center gap-2 text-xs font-bold text-slate-600">
                      <span>Quyền riêng tư:</span>
                      <select
                        value={privacy}
                        onChange={(e) => {
                          setPrivacy(e.target.value as any);
                          const v = e.target.value;
                          setPublishMode(v === "public" ? "immediate" : (v as any));
                        }}
                        className="rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-bold text-slate-700 shadow-sm"
                      >
                        <option value="public">Public (Công khai)</option>
                        <option value="unlisted">Unlisted (Không công khai)</option>
                        <option value="private">Private (Riêng tư)</option>
                      </select>
                    </div>

                    <button
                      type="button"
                      onClick={() => handlePublish(false)}
                      disabled={publishing || !isConnected}
                      className="inline-flex min-h-[44px] items-center gap-2 rounded-xl bg-red-600 px-6 py-2.5 text-xs font-bold text-white shadow-md hover:bg-red-500 disabled:opacity-50"
                    >
                      <IconUpload size={16} />
                      {publishing
                        ? "Đang đẩy lên YouTube…"
                        : publishMode === "scheduled"
                          ? `Schedule lên ${channel.channel_title}`
                          : `Publish Now lên ${channel.channel_title}`}
                    </button>
                  </div>

                  {publishError && (
                    <p className="mt-2 text-xs font-bold text-rose-600">{publishError}</p>
                  )}

                  {/* Duplicate warning modal */}
                  {duplicateWarning && (
                    <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs text-amber-900">
                      <p className="font-bold">Cảnh báo trùng lặp:</p>
                      <p className="mt-1">{duplicateWarning.message}</p>
                      {duplicateWarning.external_url && (
                        <p className="mt-1 font-mono text-[11px]">
                          Video đã có: <a href={duplicateWarning.external_url} target="_blank" rel="noreferrer" className="underline">{duplicateWarning.external_url}</a>
                        </p>
                      )}
                      <div className="mt-3 flex gap-2">
                        <button
                          type="button"
                          onClick={() => handlePublish(true)}
                          className="rounded-lg bg-amber-600 px-3 py-1.5 font-bold text-white hover:bg-amber-500"
                        >
                          Vẫn đăng (Bỏ qua cảnh báo)
                        </button>
                        <button
                          type="button"
                          onClick={() => setDuplicateWarning(null)}
                          className="rounded-lg border border-amber-300 bg-white px-3 py-1.5 font-bold text-amber-800"
                        >
                          Hủy
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}
          </Card>

          {/* Active publications monitor */}
          {activePublications.length > 0 && (
            <Card className="p-5">
              <h3 className="text-sm font-extrabold text-slate-900">Tiến trình đăng gần đây</h3>
              <div className="mt-3 space-y-3">
                {activePublications.map((pub) => (
                  <div key={pub.id} className="rounded-xl border border-slate-100 bg-slate-50 p-3 text-xs">
                    <div className="flex items-center justify-between">
                      <span className="font-bold text-slate-800 truncate">{pub.video_title || "Douyin Video"}</span>
                      <Badge tone={pub.status === "published" ? "green" : pub.status === "failed" ? "rose" : "amber"}>
                        {pub.status}
                      </Badge>
                    </div>
                    {pub.status !== "published" && pub.status !== "failed" && (
                      <div className="mt-2">
                        <ProgressBar value={pub.progress || 20} tone="indigo" />
                      </div>
                    )}
                    {pub.status === "published" && pub.external_url && (
                      <div className="mt-2">
                        <a href={pub.external_url} target="_blank" rel="noreferrer" className="font-bold text-indigo-600 hover:underline">
                          Xem trên YouTube ↗
                        </a>
                      </div>
                    )}
                    {pub.status === "failed" && (
                      <div className="mt-2 flex items-center justify-between text-rose-600">
                        <span className="truncate">{pub.error || "Thất bại"}</span>
                        <button onClick={() => handleRetryPub(pub.id)} className="font-bold underline text-indigo-600">
                          Thử lại
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>
      )}

      {/* ============================================================ */}
      {/* TAB 3: AUTO SETTINGS                                         */}
      {/* ============================================================ */}
      {activeTab === "auto" && (
        <div className="space-y-4">
          <Card className="p-5 sm:p-6">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-extrabold text-slate-900">Auto status — {channel.channel_title}</h3>
                <p className="text-xs text-slate-500">{channel.enabled ? "Auto ON — scheduler sẽ pick inventory đủ điều kiện" : "Auto OFF — scheduler tạm dừng"}</p>
              </div>
              <button type="button" onClick={() => { handleToggleEnabled(); setTimeout(fetchAutoStatus, 800); }} className={`rounded-xl px-4 py-2 text-xs font-bold text-white shadow-sm ${channel.enabled ? "bg-amber-600 hover:bg-amber-500" : "bg-emerald-600 hover:bg-emerald-500"}`}>
                {channel.enabled ? "Tắt Auto Mode" : "Bật Auto Mode"}
              </button>
            </div>
            {autoStatusLoading ? (
              <p className="mt-4 text-xs text-slate-500">Đang tải…</p>
            ) : autoStatus ? (
              <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-3"><p className="text-[11px] font-bold text-slate-400">Sources</p><p className="mt-1 text-lg font-black text-slate-900">{autoStatus.sources_count}</p></div>
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-3"><p className="text-[11px] font-bold text-slate-400">Enabled</p><p className="mt-1 text-lg font-black text-emerald-600">{autoStatus.enabled_sources}</p></div>
                <div className="rounded-xl border border-rose-200 bg-rose-50 p-3"><p className="text-[11px] font-bold text-rose-500">Needs re-auth</p><p className="mt-1 text-lg font-black text-rose-700">{autoStatus.needs_reauth_sources}</p></div>
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-3"><p className="text-[11px] font-bold text-slate-400">Today</p><p className="mt-1 text-lg font-black text-slate-900">{autoStatus.today_published} / {autoStatus.today_limit}</p></div>
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-3"><p className="text-[11px] font-bold text-slate-400">Queue</p><p className="mt-1 text-lg font-black text-slate-900">{autoStatus.queue_count}</p></div>
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-3"><p className="text-[11px] font-bold text-slate-400">Failed</p><p className="mt-1 text-lg font-black text-rose-600">{autoStatus.failed_count}</p></div>
                <div className="rounded-xl border border-amber-200 bg-amber-50 p-3"><p className="text-[11px] font-bold text-amber-600">Held</p><p className="mt-1 text-lg font-black text-amber-800">{autoStatus.held_count}</p></div>
                <div className="rounded-xl border border-rose-200 bg-rose-50 p-3"><p className="text-[11px] font-bold text-rose-600">Rejected</p><p className="mt-1 text-lg font-black text-rose-700">{autoStatus.rejected_count}</p></div>
              </div>
            ) : null}
            {autoStatus && (
              <div className="mt-4 flex flex-wrap items-center gap-3 text-xs text-slate-500">
                <span>Last scan: <strong className="text-slate-700">{autoStatus.last_scan_at ? new Date(autoStatus.last_scan_at).toLocaleString() : "—"}</strong></span>
                <span>Next scan: <strong className="text-slate-700">{autoStatus.next_scan_at ? new Date(autoStatus.next_scan_at).toLocaleString() : "—"}</strong></span>
                <button type="button" onClick={fetchAutoStatus} className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-bold text-slate-600 hover:bg-slate-50"><IconRefresh size={12} />Làm mới</button>
              </div>
            )}
          </Card>
          <Card className="p-5 sm:p-6">
            <form onSubmit={handleSaveAuto} className="space-y-4">
              <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                <div>
                  <h3 className="text-sm font-extrabold text-slate-900">Cấu hình Auto Schedule (Kênh {channel.channel_title})</h3>
                  <p className="text-xs text-slate-500">Scheduler hoạt động độc lập theo cấu hình riêng của workspace này</p>
                </div>
              </div>
              {autoSuccess && <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs font-bold text-emerald-800">✓ Đã lưu cài đặt Auto Mode thành công!</div>}
              <div><label className="text-xs font-bold text-slate-700">Daily Upload Limit (videos/ngày)</label><input type="number" min={1} max={50} value={autoLimit} onChange={(e) => setAutoLimit(Number(e.target.value) || 1)} className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm font-semibold text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none" /></div>
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                <p className="text-xs font-extrabold text-slate-700">Publishing strategy</p>
                <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {[
                    { v: "immediate", t: "A. Upload immediately", d: "Public ngay khi worker xong" },
                    { v: "scheduled", t: "B. YouTube scheduled", d: "Private + publishAt theo slots" },
                  ].map((o) => (
                    <button
                      key={o.v}
                      type="button"
                      onClick={() => setAutoPublishMode(o.v as "immediate" | "scheduled")}
                      className={`rounded-xl border px-3 py-2 text-left ${autoPublishMode === o.v ? "border-indigo-500 bg-white ring-2 ring-indigo-500/20" : "border-slate-200 bg-white"}`}
                    >
                      <span className="block text-xs font-bold text-slate-900">{o.t}</span>
                      <span className="block text-[11px] text-slate-500">{o.d}</span>
                    </button>
                  ))}
                </div>
                <label className="mt-2 block text-[11px] font-bold text-slate-600">
                  Default publish mode (kênh này)
                  <select
                    value={autoPublishMode}
                    onChange={(e) => setAutoPublishMode(e.target.value as "immediate" | "scheduled" | "private" | "unlisted")}
                    className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-bold"
                  >
                    <option value="immediate">Publish immediately</option>
                    <option value="scheduled">Schedule</option>
                    <option value="private">Private</option>
                    <option value="unlisted">Unlisted</option>
                  </select>
                </label>
              </div>
              <div><label className="text-xs font-bold text-slate-700">Upload Slots (Giờ xuất bản, phân cách bằng dấu phẩy)</label><input type="text" value={autoSlots} onChange={(e) => setAutoSlots(e.target.value)} placeholder="09:00, 12:00, 18:00, 21:00" className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 font-mono text-sm font-bold text-indigo-600 shadow-sm focus:border-indigo-500 focus:outline-none" /><p className="mt-1 text-[11px] text-slate-500">Định dạng 24h: <code>09:00, 12:00, 18:00, 21:00</code> — mỗi kênh lịch riêng</p></div>
              <div><label className="text-xs font-bold text-slate-700">Múi giờ (Timezone)</label><input type="text" value={autoTimezone} onChange={(e) => setAutoTimezone(e.target.value)} placeholder="Asia/Ho_Chi_Minh" className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm font-semibold text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none" /></div>
              <div className="pt-2"><button type="submit" disabled={savingAuto} className="inline-flex min-h-[44px] items-center gap-2 rounded-xl bg-indigo-600 px-6 py-2.5 text-xs font-bold text-white shadow-md hover:bg-indigo-500 disabled:opacity-50">{savingAuto ? "Đang lưu…" : "Lưu cài đặt Auto"}</button></div>
            </form>
          </Card>
        </div>
      )}

      {/* ============================================================ */}
      {/* TAB 4: SOURCES                                               */}
      {/* ============================================================ */}
      {activeTab === "sources" && (
        <div className="space-y-6">
          {/* Global Platform Accounts (shared login) */}
          <Card className="p-5 sm:p-6">
            <h3 className="text-sm font-extrabold text-slate-900">Platform Accounts — Shared Login</h3>
            <p className="text-xs text-slate-500">Một tài khoản Douyin/Facebook đăng nhập một lần, dùng chung cho tất cả pipeline.</p>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              {globalAccounts.map((acct) => (
                <div key={acct.platform} className={`rounded-xl border p-3 ${acct.connected ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"}`}>
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-extrabold uppercase text-slate-700">{acct.platform}</span>
                    <Badge tone={acct.connected ? "green" : "amber"}>{acct.connected ? "Connected ✅" : "Needs login"}</Badge>
                  </div>
                  <p className="mt-1 text-[11px] text-slate-500">Used by {acct.used_by_sources ?? 0} sources{acct.last_verified_at ? ` · Last verified: ${new Date(acct.last_verified_at).toLocaleString()}` : ""}</p>
                  {acct.platform === "douyin" && (
                    <div className="mt-3">
                      {!acct.connected ? (
                        <div className="space-y-2">
                          <textarea value={globalCookieDraft} onChange={(e) => setGlobalCookieDraft(e.target.value)} rows={3} placeholder="Dán Douyin cookies.txt hoặc JSON export — không log, chỉ lưu mã hóa" className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 font-mono text-[11px] text-slate-700" />
                          <div className="flex gap-2">
                            <button type="button" onClick={handleSaveGlobalCookie} disabled={globalCookieBusy || !globalCookieDraft.trim()} className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-bold text-white disabled:opacity-50">Connect / Update Cookie</button>
                            <button type="button" onClick={handleTestGlobalCookie} disabled={globalCookieBusy} className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-bold text-slate-600">Test Login</button>
                          </div>
                        </div>
                      ) : (
                        <div className="flex gap-2">
                          <button type="button" onClick={handleTestGlobalCookie} disabled={globalCookieBusy} className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-bold text-slate-600">Test Login</button>
                          <button type="button" onClick={() => setShowGlobalCookieEditor(!showGlobalCookieEditor)} className="rounded-lg border border-indigo-200 bg-white px-3 py-1.5 text-xs font-bold text-indigo-600">Update Cookie</button>
                          <button type="button" onClick={handleDeleteGlobalCookie} disabled={globalCookieBusy} className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-1.5 text-xs font-bold text-rose-700">Disconnect</button>
                        </div>
                      )}
                      {showGlobalCookieEditor && acct.connected && (
                        <div className="mt-3">
                          <textarea value={globalCookieDraft} onChange={(e) => setGlobalCookieDraft(e.target.value)} rows={3} placeholder="Dán cookie mới…" className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 font-mono text-[11px] text-slate-700" />
                          <div className="mt-2 flex gap-2">
                            <button type="button" onClick={handleSaveGlobalCookie} disabled={globalCookieBusy || !globalCookieDraft.trim()} className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-bold text-white">Lưu</button>
                            <button type="button" onClick={() => setShowGlobalCookieEditor(false)} className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-bold text-slate-600">Hủy</button>
                          </div>
                        </div>
                      )}
                      {globalCookieMsg && <p className={`mt-2 text-[11px] font-bold ${globalCookieMsg.ok ? "text-emerald-600" : "text-rose-600"}`}>{globalCookieMsg.text}</p>}
                      {globalCookieBusy && <p className="mt-1 text-[11px] text-slate-500">Đang xử lý…</p>}
                    </div>
                  )}
                  {acct.platform === "facebook" && !acct.connected && <p className="mt-2 text-[11px] text-slate-500">Facebook provider stub — architecture ready, chưa cần login thật.</p>}
                </div>
              ))}
            </div>
          </Card>

          {/* Add Source Form */}
          <Card className="p-5 sm:p-6">
            <h3 className="text-sm font-extrabold text-slate-900">Thêm tác giả Douyin vào kênh {channel.channel_title}</h3>
            <p className="text-xs text-slate-500">
              Tác giả sẽ chỉ thuộc về workspace này. Video cào về sẽ chỉ lưu vào kho của kênh này.
            </p>

            <form onSubmit={handleAddSource} className="mt-4 space-y-3">
              <div className="grid gap-3 sm:grid-cols-3">
                <select value={sourcePlatform} onChange={(e) => setSourcePlatform(e.target.value as "douyin" | "facebook")} className="rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-xs font-bold text-slate-700">
                  <option value="douyin">Douyin</option>
                  <option value="facebook">Facebook</option>
                </select>
                <input type="text" value={sourceName} onChange={(e) => setSourceName(e.target.value)} placeholder="Tên tác giả / Page" className="rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-xs text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none" />
                <input type="text" value={sourceUrl} onChange={(e) => setSourceUrl(e.target.value)} placeholder={sourcePlatform === "facebook" ? "Link Facebook Page/Profile" : "Link Douyin (https://v.douyin.com/...)"} className="rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-xs text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none" />
              </div>
              <div className="grid gap-3 sm:grid-cols-4">
                <div><label className="text-[11px] font-bold text-slate-600">Scan interval (phút)</label><input type="number" min={5} max={1440} value={sourceScanInterval} onChange={(e) => setSourceScanInterval(e.target.value)} className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-900" /></div>
                <div><label className="text-[11px] font-bold text-slate-600">Max videos/ngày</label><input type="number" min={0} max={50} value={sourceMaxPerDay} onChange={(e) => setSourceMaxPerDay(e.target.value)} className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-900" /></div>
                <div><label className="text-[11px] font-bold text-slate-600">Start mode</label><select value={sourceStartMode} onChange={(e) => setSourceStartMode(e.target.value as "new_only" | "last_n")} className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-bold text-slate-700"><option value="new_only">NEW_ONLY (chỉ video mới)</option><option value="last_n">LAST_N (giữ N mới nhất)</option></select></div>
                <div><label className="text-[11px] font-bold text-slate-600">Initial limit (LAST_N)</label><input type="number" min={1} max={50} value={sourceInitialLimit} onChange={(e) => setSourceInitialLimit(e.target.value)} className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-900" /></div>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div><label className="text-[11px] font-bold text-slate-600">Include keywords (phân cách dấu phẩy)</label><input type="text" value={sourceIncludeKw} onChange={(e) => setSourceIncludeKw(e.target.value)} placeholder="ví dụ: dance, street" className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-900" /></div>
                <div><label className="text-[11px] font-bold text-slate-600">Exclude keywords</label><input type="text" value={sourceExcludeKw} onChange={(e) => setSourceExcludeKw(e.target.value)} placeholder="ví dụ: gym, food" className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-900" /></div>
              </div>
              <button type="submit" disabled={addingSource || !sourceName.trim() || !sourceUrl.trim()} className="inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-xl bg-indigo-600 px-5 py-2 text-xs font-bold text-white shadow-sm hover:bg-indigo-500 disabled:opacity-50">
                <IconPlus size={15} />
                {addingSource ? "Đang thêm…" : "Thêm Source"}
              </button>
            </form>

            {sourceError && (
              <p className="mt-2 text-xs font-bold text-rose-600">{sourceError}</p>
            )}
          </Card>

          {/* Sources List — per-source cookie + scan controls */}
          <Card className="p-5 sm:p-6">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <h3 className="text-sm font-extrabold text-slate-900">Danh sách tác giả trong workspace ({workspaceSources.length || detail.sources?.length || 0})</h3>
              <div className="flex flex-wrap items-center gap-2">
                {quota && (
                  <span
                    className={`inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] font-bold ${
                      quota.status === "quota_exhausted"
                        ? "bg-rose-50 text-rose-700"
                        : quota.status === "low"
                          ? "bg-amber-50 text-amber-700"
                          : "bg-emerald-50 text-emerald-700"
                    }`}
                    title="Hạn mức RapidAPI (1 trang = 1 request)"
                  >
                    Quota RapidAPI: {quota.remaining}/{quota.limit}
                    {quota.month ? ` · ${quota.month}` : ""}
                  </span>
                )}
                <button type="button" onClick={() => { fetchWorkspaceSources(); fetchQuota(); reloadDetail(); }} className="rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-bold text-slate-600 hover:bg-slate-50">
                  <IconRefresh size={11} /> Làm mới
                </button>
              </div>
            </div>
            {(workspaceSources.length === 0 && (!detail.sources || detail.sources.length === 0)) ? (
              <p className="mt-4 text-xs text-slate-500">Chưa có tác giả nào. Hãy thêm link Douyin ở trên.</p>
            ) : (
              <div className="mt-4 divide-y divide-slate-100">
                {(workspaceSources.length ? workspaceSources : (detail.sources as unknown as WorkspaceSourceItem[])).map((s) => {
                  const source = s as WorkspaceSourceItem;
                  const isPaused = source.enabled === false;
                  const platform = (source as unknown as { platform?: string }).platform || "douyin";
                  const douyinAccount = globalAccounts.find((a) => a.platform === "douyin");
                  const needsGlobalAuth = platform === "douyin" && douyinAccount && !douyinAccount.connected;
                  const importStatus = (source.initial_import_status || "pending").toLowerCase();
                  const importBusy = importingSourceId === source.id;
                  const canResume = (importStatus === "paused_quota" || importStatus === "paused") && !!source.initial_import_cursor;
                  const showRefresh = importStatus === "completed";
                  const importLabel =
                    importStatus === "completed" ? "Đã import"
                    : importStatus === "running" ? "Đang import…"
                    : importStatus === "paused_quota" ? "Hết quota — có thể chạy tiếp"
                    : importStatus === "paused" ? "Tạm dừng — có thể chạy tiếp"
                    : importStatus === "failed" ? "Import lỗi"
                    : "Chưa import";
                  const importTone =
                    importStatus === "completed" ? "green"
                    : importStatus === "failed" ? "red"
                    : importStatus === "running" || importStatus === "paused_quota" || importStatus === "paused" ? "amber"
                    : "slate";
                  return (
                    <div key={source.id} className="flex flex-col gap-2 py-3.5 text-xs">
                      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="font-extrabold text-slate-900 text-sm">{source.name}</span>
                            <span className={`rounded-md px-1.5 py-0.5 text-[10px] font-bold ${platform === "facebook" ? "bg-blue-50 text-blue-700" : "bg-slate-100 text-slate-700"}`}>{platform === "facebook" ? "Facebook" : "Douyin"}</span>
                          </div>
                          <p className="mt-0.5 font-mono text-[11px] text-slate-400 truncate max-w-md">{source.profile_url}</p>
                          <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                            <span>Kho: <strong className="text-slate-800">{source.video_count ?? 0}</strong> video</span>
                            <span>· Trạng thái: <Badge tone={source.status === "syncing" || source.status === "running" ? "amber" : source.status === "auth_required" ? "red" : "slate"}>{source.status}</Badge></span>
                            <span>· Import: <Badge tone={importTone}>{importLabel}</Badge></span>
                            {platform === "douyin" && (
                              <span className="rounded-md bg-indigo-50 px-1.5 py-0.5 text-[10px] font-bold text-indigo-700">
                                {(source.feed_provider || "rapidapi_justone") === "rapidapi_justone" ? "RapidAPI JustOne" : source.feed_provider}
                              </span>
                            )}
                            {(importStatus === "running" || importStatus === "paused_quota" || importStatus === "paused") && (
                              <span>· Đã đọc <strong className="text-slate-800">{source.initial_import_pages ?? 0}</strong> trang / <strong className="text-slate-800">{source.initial_import_videos ?? 0}</strong> video</span>
                            )}
                            {needsGlobalAuth && <span className="rounded-md bg-amber-50 px-1.5 py-0.5 font-bold text-amber-700">Douyin account needs login (global)</span>}
                            {isPaused && <Badge tone="amber">Paused</Badge>}
                          </div>
                          {(source.initial_import_last_error || source.inventory_sync_error) && <p className="mt-1 text-[11px] font-semibold text-rose-600 line-clamp-2">{source.initial_import_last_error || source.inventory_sync_error}</p>}
                        </div>
                        <div className="flex flex-wrap items-center gap-1.5">
                          {!showRefresh && (
                            <button type="button" onClick={() => handleInitialImport(source.id, canResume)} disabled={importBusy || importStatus === "running"} className="inline-flex min-h-[36px] items-center gap-1 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-xs font-bold text-indigo-700 hover:bg-indigo-100 disabled:opacity-50">
                              <IconUpload size={13} /> {importBusy ? "Đang chạy…" : canResume ? "Chạy tiếp import" : "Import ban đầu"}
                            </button>
                          )}
                          {showRefresh && (
                            <button type="button" onClick={() => handleSyncSource(source.id)} disabled={syncingSourceId === source.id} className="inline-flex min-h-[36px] items-center gap-1 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-bold text-slate-700 hover:bg-slate-50 disabled:opacity-50">
                              <IconRefresh size={13} /> {syncingSourceId === source.id ? "Đang cập nhật…" : "Cập nhật video mới"}
                            </button>
                          )}
                          <button type="button" onClick={() => handlePauseSource(source.id, !isPaused)} className={`inline-flex min-h-[36px] items-center rounded-lg border px-3 py-1.5 text-xs font-bold ${isPaused ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-amber-200 bg-amber-50 text-amber-700"}`}>
                            {isPaused ? "Resume" : "Pause"}
                          </button>
                          <button type="button" onClick={() => handleDeleteSource(source.id)} disabled={deletingSourceId === source.id} className="inline-flex min-h-[36px] items-center gap-1 rounded-lg border border-rose-200 bg-rose-50 px-3 py-1.5 text-xs font-bold text-rose-700 hover:bg-rose-100 disabled:opacity-50">
                            <IconX size={13} /> Xóa
                          </button>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </Card>
        </div>
      )}

      {/* ============================================================ */}
      {/* TAB 5: INVENTORY                                             */}
      {/* ============================================================ */}
      {activeTab === "inventory" && (
        <div className="space-y-4">
          {/* Filters */}
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            {["all", "new", "backlog", "scheduled", "published", "held", "rejected", "baseline", "content_mismatch"].map((st) => (
              <button
                key={st}
                type="button"
                onClick={() => setInventoryFilter(st)}
                className={`rounded-xl px-3 py-1.5 font-bold transition ${
                  inventoryFilter === st
                    ? "bg-indigo-600 text-white shadow-sm"
                    : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                }`}
              >
                {st.toUpperCase()}
              </button>
            ))}
          </div>

          {/* Videos Grid */}
          {filteredInventory.length === 0 ? (
            <Card className="p-8 text-center text-xs text-slate-500">
              Không có video nào với bộ lọc này trong workspace {channel.channel_title}.
            </Card>
          ) : (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {filteredInventory.map((item) => (
                <div key={item.id} className="flex gap-3 rounded-2xl border border-slate-200 bg-white p-3 shadow-sm text-xs">
                  <div className="relative aspect-[9/16] w-20 shrink-0 overflow-hidden rounded-xl bg-slate-900">
                    {item.thumbnail_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={item.thumbnail_url} alt="" className="h-full w-full object-cover" />
                    ) : (
                      <div className="flex h-full w-full items-center justify-center text-[10px] text-slate-500">No img</div>
                    )}
                  </div>

                  <div className="flex flex-1 flex-col justify-between min-w-0">
                    <div>
                      <div className="flex items-center justify-between gap-1">
                        <Badge tone={item.status === "published" ? "green" : item.status === "content_mismatch" ? "rose" : "slate"}>
                          {item.status}
                        </Badge>
                      </div>
                      <p className="mt-1 font-bold text-slate-900 line-clamp-2">{item.title || "Douyin Video"}</p>
                      <p className="mt-1 font-mono text-[10px] text-slate-400">ID: {item.video_id}</p>
                    </div>

                    <div className="mt-2 flex items-center justify-between pt-2 border-t border-slate-100">
                      <a href={item.url} target="_blank" rel="noreferrer" className="text-[11px] font-bold text-slate-500 hover:underline">
                        Douyin ↗
                      </a>
                      <button
                        type="button"
                        onClick={() => handleQuickPublishInventory(item)}
                        className="rounded-lg bg-indigo-50 px-2.5 py-1 text-[11px] font-bold text-indigo-700 hover:bg-indigo-100"
                      >
                        Publish →
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ============================================================ */}
      {/* TAB 6: QUEUE                                                 */}
      {/* ============================================================ */}
      {activeTab === "queue" && (
        <Card className="p-5 sm:p-6">
          <div className="flex items-center justify-between border-b border-slate-100 pb-3">
            <div>
              <h3 className="text-sm font-extrabold text-slate-900">Hàng đợi xuất bản (Queue)</h3>
              <p className="text-xs text-slate-500">Chỉ hiển thị các video đang xử lý / lên lịch cho {channel.channel_title}</p>
            </div>
            <button onClick={reloadDetail} className="rounded-lg border border-slate-200 bg-white p-2 hover:bg-slate-50">
              <IconRefresh size={14} />
            </button>
          </div>

          {(!detail.queue || detail.queue.length === 0) ? (
            <p className="mt-6 text-xs text-slate-500 text-center">Hàng đợi trống. Video sẽ xuất hiện ở đây khi Auto chạy hoặc đăng thủ công.</p>
          ) : (
            <div className="mt-4 divide-y divide-slate-100">
              {detail.queue.map((item) => (
                <div key={item.id} className="flex items-center justify-between py-3 text-xs">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="h-10 w-10 shrink-0 rounded-lg bg-slate-900 overflow-hidden">
                      {item.thumbnail && <img src={item.thumbnail} alt="" className="h-full w-full object-cover" />}
                    </div>
                    <div className="min-w-0">
                      <p className="font-bold text-slate-900 truncate">{item.video_title || "Video"}</p>
                      <div className="flex items-center gap-2 text-[11px] text-slate-400">
                        <span>Status: <Badge tone="amber">{item.status}</Badge></span>
                        {item.created_at && <span>{new Date(item.created_at).toLocaleTimeString()}</span>}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    {item.status === "failed" && (
                      <button onClick={() => handleRetryPub(item.id)} className="font-bold text-indigo-600 hover:underline">
                        Thử lại
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      {/* ============================================================ */}
      {/* TAB: UPCOMING / SCHEDULED (native YouTube publishAt)          */}
      {/* ============================================================ */}
      {activeTab === "upcoming" && (
        <div className="space-y-4">
          <UpcomingScheduled destinationId={channel.destination_id} />
        </div>
      )}

      {/* ============================================================ */}
      {/* TAB: ANALYTICS (owned channel, DB/cache first)               */}
      {/* ============================================================ */}
      {activeTab === "analytics" && (
        <Card className="p-5 sm:p-6">
          <ChannelAnalytics destinationId={channel.destination_id} />
        </Card>
      )}

      {/* ============================================================ */}
      {/* TAB: AI RESEARCH (trend radar + apply to metadata)           */}
      {/* ============================================================ */}
      {activeTab === "research" && (
        <Card className="p-5 sm:p-6">
          <ChannelResearch
            destinationId={channel.destination_id}
            onApply={(bundle) => {
              if (bundle.title) setTitle(bundle.title);
              if (bundle.hashtags && bundle.hashtags.length > 0) {
                setHashtags((prev) => {
                  const merged = `${prev} ${bundle.hashtags!.join(" ")}`.trim().split(/\s+/);
                  return Array.from(new Set(merged)).join(" ");
                });
              }
              if (bundle.keywords && bundle.keywords.length > 0) {
                setDescription((prev) => `${prev}\n\nKeywords: ${bundle.keywords!.join(", ")}`.trim());
              }
              setActiveTab("manual");
            }}
          />
        </Card>
      )}

      {/* ============================================================ */}
      {/* TAB: CHANNEL DNA (AI Growth → Channel DNA)                   */}
      {/* ============================================================ */}
      {activeTab === "dna" && (
        <Card className="p-5 sm:p-6">
          <ChannelDNA destinationId={channel.destination_id} />
        </Card>
      )}

      {/* ============================================================ */}
      {/* TAB 7: PUBLISHED                                             */}
      {/* ============================================================ */}
      {activeTab === "published" && (
        <Card className="p-5 sm:p-6">
          <div className="flex items-center justify-between border-b border-slate-100 pb-3">
            <div>
              <h3 className="text-sm font-extrabold text-slate-900">Lịch sử video đã xuất bản ({detail.published?.length || 0})</h3>
              <p className="text-xs text-slate-500">Chỉ hiển thị các video đã xuất bản thành công lên kênh {channel.channel_title}</p>
            </div>
            <button onClick={reloadDetail} className="rounded-lg border border-slate-200 bg-white p-2 hover:bg-slate-50">
              <IconRefresh size={14} />
            </button>
          </div>

          {(!detail.published || detail.published.length === 0) ? (
            <p className="mt-6 text-xs text-slate-500 text-center">Chưa có video nào được đăng lên kênh này.</p>
          ) : (
            <div className="mt-4 divide-y divide-slate-100">
              {detail.published.map((item) => (
                <div key={item.id} className="flex items-center justify-between py-3 text-xs">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="h-10 w-10 shrink-0 rounded-lg bg-slate-900 overflow-hidden">
                      {item.thumbnail && <img src={item.thumbnail} alt="" className="h-full w-full object-cover" />}
                    </div>
                    <div className="min-w-0">
                      <p className="font-bold text-slate-900 truncate">{item.video_title || "Video"}</p>
                      <span className="text-[11px] text-slate-400">
                        Đã đăng lúc: {item.published_at ? new Date(item.published_at).toLocaleString() : "Recently"}
                      </span>
                    </div>
                  </div>

                  <div>
                    {item.external_url ? (
                      <a
                        href={item.external_url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex min-h-[36px] items-center gap-1 rounded-lg bg-red-50 px-3 py-1.5 font-bold text-red-700 hover:bg-red-100"
                      >
                        YouTube ↗
                      </a>
                    ) : (
                      <Badge tone="green">Published</Badge>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      {/* ============================================================ */}
      {
        /* === TAB: COMMENTS (AI Comment Reply, independent worker) === */
      }
      {activeTab === "comments" && (
        <div className="space-y-6">
          {commentNotice && (
            <div className="rounded-xl border border-indigo-200 bg-indigo-50 p-3 text-xs font-bold text-indigo-900">
              {commentNotice}
            </div>
          )}

          <Card className="p-5 sm:p-6">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 pb-3">
              <div>
                <h3 className="text-sm font-extrabold text-slate-900">
                  Bình luận YouTube ({commentMeta?.total ?? detail.comment_count ?? 0})
                </h3>
                <p className="text-xs text-slate-500">
                  AI trả lời bình luận dùng prompt riêng của kênh — không liên quan tới prompt tạo title/description/hashtags.
                </p>
              </div>
              <div className="flex items-center gap-2">
                <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-[11px] font-black text-slate-700">
                  AI Reply: {(commentMeta?.mode || crMode || "off").toUpperCase()}
                </span>
                <button
                  type="button"
                  onClick={handleScanComments}
                  disabled={commentsLoading || scanningComments}
                  className="inline-flex min-h-[40px] items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-bold text-slate-700 shadow-sm hover:bg-slate-50 disabled:opacity-50"
                >
                  <IconRefresh size={14} />
                  {scanningComments ? "Đang quét…" : "Quét bình luận"}
                </button>
              </div>
            </div>

            {commentMeta && !commentMeta.oauth_ready && (
              <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs font-bold text-amber-900">
                Reconnect required for comment replies — kênh này chưa cấp quyền
                youtube.force-ssl ({commentMeta.oauth_reason || "YOUTUBE_SCOPE_MISSING"}).
                Hãy Reconnect OAuth cho kênh này ở tab Settings.
              </div>
            )}

            <div className="mt-4 grid grid-cols-3 gap-2 sm:grid-cols-6">
              {[
                { label: "New", value: commentMeta?.stats?.new || 0 },
                { label: "Ready", value: commentMeta?.stats?.ready_to_reply || 0 },
                { label: "Replied today", value: commentMeta?.replies_today || 0 },
                { label: "Held", value: commentMeta?.stats?.held || 0 },
                { label: "Failed", value: commentMeta?.stats?.failed || 0 },
                { label: "Limit", value: commentMeta?.daily_limit ?? crDailyLimit },
              ].map((s) => (
                <div
                  key={s.label}
                  className="rounded-xl border border-slate-200 bg-white p-3 shadow-sm"
                >
                  <span className="text-[10px] font-bold text-slate-400">{s.label}</span>
                  <p className="mt-0.5 text-lg font-black text-slate-900">{s.value}</p>
                </div>
              ))}
            </div>

            <div className="mt-4 flex flex-wrap gap-2">
              {[
                { key: "", label: "Tất cả" },
                { key: "new", label: "New" },
                { key: "ready_to_reply", label: "Ready" },
                { key: "replied", label: "Replied" },
                { key: "held", label: "Held" },
                { key: "failed", label: "Failed" },
              ].map((f) => (
                <button
                  key={f.key || "all"}
                  type="button"
                  onClick={() => {
                    setCommentFilter(f.key);
                    fetchComments(f.key);
                  }}
                  className={`rounded-full border px-3.5 py-1.5 text-[11px] font-bold transition ${
                    commentFilter === f.key
                      ? "border-indigo-300 bg-indigo-50 text-indigo-700"
                      : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                  }`}
                >
                  {f.label}
                </button>
              ))}
            </div>
          </Card>

          {commentsLoading && comments.length === 0 ? (
            <Card className="p-6 text-center text-xs font-bold text-slate-500">
              Đang tải bình luận…
            </Card>
          ) : comments.length === 0 ? (
            <Card className="p-6 text-center text-xs font-bold text-slate-500">
              Chưa có bình luận nào. Bấm “Quét bình luận” để lấy bình luận mới từ YouTube.
            </Card>
          ) : (
            <div className="space-y-3">
              {comments.map((c) => (
                <Card key={c.id} className="p-4 sm:p-5">
                  <div className="flex items-start gap-3">
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-violet-600 text-xs font-black text-white">
                      {(c.author_name || "?").slice(0, 1).toUpperCase()}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-xs font-extrabold text-slate-900">
                          {c.author_name || "Ẩn danh"}
                        </span>
                        <span className="text-[10px] font-semibold text-slate-400">
                          {formatTime(c.published_at)}
                        </span>
                        <span
                          className={`rounded-full border px-2 py-0.5 text-[10px] font-black ${commentStatusTone(
                            c.status,
                          )}`}
                        >
                          {c.status}
                        </span>
                        {c.ai_classification ? (
                          <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-black text-slate-600">
                            {c.ai_classification.toUpperCase()}
                            {c.ai_confidence != null
                              ? ` · ${Math.round(c.ai_confidence * 100)}%`
                              : ""}
                          </span>
                        ) : null}
                      </div>
                      <p className="mt-1.5 whitespace-pre-wrap text-sm text-slate-800">
                        {c.text_original}
                      </p>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-[10px] font-semibold text-slate-400">
                        <span>Video: {c.video_title || c.video_id}</span>
                        {c.like_count ? <span>· {c.like_count} like</span> : null}
                        {c.ai_reason ? <span>· {c.ai_reason}</span> : null}
                      </div>

                      {editingCommentId === c.id ? (
                        <div className="mt-3">
                          <textarea
                            rows={3}
                            value={editReplyText}
                            onChange={(e) => setEditReplyText(e.target.value)}
                            className="w-full rounded-xl border border-slate-200 bg-white p-3 text-sm text-slate-800 shadow-sm focus:border-indigo-500 focus:outline-none"
                          />
                          <div className="mt-2 flex gap-2">
                            <button
                              type="button"
                              disabled={busyCommentId === c.id || !editReplyText.trim()}
                              onClick={() => handleSendCommentReply(c.id, editReplyText)}
                              className="inline-flex min-h-[38px] items-center gap-1.5 rounded-xl bg-indigo-600 px-4 py-2 text-xs font-bold text-white shadow-sm hover:bg-indigo-500 disabled:opacity-50"
                            >
                              <IconCheck size={14} />
                              Gửi reply
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                setEditingCommentId(null);
                                setEditReplyText("");
                              }}
                              className="inline-flex min-h-[38px] items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-bold text-slate-600 shadow-sm hover:bg-slate-50"
                            >
                              <IconX size={14} />
                              Huỷ
                            </button>
                          </div>
                        </div>
                      ) : (
                        <>
                          {c.reply_text || c.ai_reply ? (
                            <div className="mt-3 rounded-xl border border-indigo-100 bg-indigo-50/60 p-3">
                              <span className="text-[10px] font-black uppercase tracking-wide text-indigo-500">
                                Suggested reply
                              </span>
                              <p className="mt-1 text-sm text-slate-800">
                                {c.reply_text || c.ai_reply}
                              </p>
                            </div>
                          ) : null}

                          <div className="mt-3 flex flex-wrap gap-2">
                            {c.status !== "replied" && c.status !== "ignored" ? (
                              <button
                                type="button"
                                disabled={busyCommentId === c.id}
                                onClick={() =>
                                  handleSendCommentReply(
                                    c.id,
                                    (c.reply_text || c.ai_reply || "").trim(),
                                  )
                                }
                                className="inline-flex min-h-[38px] items-center gap-1.5 rounded-xl bg-indigo-600 px-3.5 py-2 text-xs font-bold text-white shadow-sm hover:bg-indigo-500 disabled:opacity-50"
                              >
                                <IconCheck size={14} />
                                Reply
                              </button>
                            ) : null}
                            <button
                              type="button"
                              onClick={() => {
                                setEditingCommentId(c.id);
                                setEditReplyText(c.reply_text || c.ai_reply || "");
                              }}
                              className="inline-flex min-h-[38px] items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-bold text-slate-700 shadow-sm hover:bg-slate-50"
                            >
                              Edit
                            </button>
                            <button
                              type="button"
                              disabled={busyCommentId === c.id}
                              onClick={() => handleGenerateComment(c.id)}
                              className="inline-flex min-h-[38px] items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-bold text-slate-700 shadow-sm hover:bg-slate-50 disabled:opacity-50"
                            >
                              <IconRefresh size={14} />
                              Regenerate
                            </button>
                            <button
                              type="button"
                              disabled={busyCommentId === c.id}
                              onClick={() => handleSkipComment(c.id)}
                              className="inline-flex min-h-[38px] items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-bold text-slate-500 shadow-sm hover:bg-slate-50 disabled:opacity-50"
                            >
                              <IconX size={14} />
                              Ignore
                            </button>
                          </div>
                        </>
                      )}
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          )}
        </div>
      )}

      {/* TAB 8: AI PROFILE (Requirement 7)                            */}
      {/* ============================================================ */}
      {activeTab === "ai_profile" && (
        <Card className="p-5 sm:p-6">
          <form onSubmit={handleSaveAiProfile} className="space-y-4">
            <div className="border-b border-slate-100 pb-3">
              <h3 className="text-sm font-extrabold text-slate-900">Cấu hình AI Profile (Kênh {channel.channel_title})</h3>
              <p className="text-xs text-slate-500">
                Bộ quy tắc này chỉ áp dụng cho kênh này khi tạo tiêu đề, mô tả và hashtags.
              </p>
            </div>

            {aiSuccess && (
              <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs font-bold text-emerald-800">
                ✓ Đã lưu cấu hình AI Profile thành công!
              </div>
            )}

            <div>
              <label className="text-xs font-bold text-slate-700">Channel Niche / Chủ đề trọng tâm</label>
              <input
                type="text"
                value={aiNiche}
                onChange={(e) => setAiNiche(e.target.value)}
                placeholder="Ví dụ: Male dance performance, choreography, dance covers, Asian urban dance..."
                className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-xs text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none"
              />
            </div>

            <div>
              <label className="text-xs font-bold text-slate-700">Ngôn ngữ Metadata (Language)</label>
              <input
                type="text"
                value={aiLanguage}
                onChange={(e) => setAiLanguage(e.target.value)}
                placeholder="en, vi, zh, ja..."
                className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-xs text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none"
              />
            </div>

            <div>
              <label className="text-xs font-bold text-slate-700">Fixed Hashtags (Bắt buộc, cách nhau bởi dấu cách)</label>
              <input
                type="text"
                value={aiFixedTags}
                onChange={(e) => setAiFixedTags(e.target.value)}
                placeholder="#dance #choreography"
                className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 font-mono text-xs font-bold text-indigo-600 shadow-sm focus:border-indigo-500 focus:outline-none"
              />
            </div>

            <div>
              <label className="text-xs font-bold text-slate-700">Adaptive Hashtags (Gợi ý ưu tiên cho AI)</label>
              <input
                type="text"
                value={aiAdaptiveTags}
                onChange={(e) => setAiAdaptiveTags(e.target.value)}
                placeholder="#dancecover #dancer #dancevideo #urbandance #kpopdance"
                className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 font-mono text-xs font-bold text-indigo-600 shadow-sm focus:border-indigo-500 focus:outline-none"
              />
            </div>

            <div>
              <label className="text-xs font-bold text-slate-700">Prompt Override / AI System Prompt</label>
              <textarea
                rows={12}
                value={aiPrompt}
                onChange={(e) => setAiPrompt(e.target.value)}
                placeholder="Nhập toàn bộ System Prompt chi tiết về Channel Identity, Content Selection, Title Rules, Description Rules, Quality Rule..."
                className="mt-1 w-full rounded-xl border border-slate-200 bg-white p-3 font-mono text-xs text-slate-800 shadow-sm focus:border-indigo-500 focus:outline-none"
              />
            </div>

            <div className="pt-2">
              <button
                type="submit"
                disabled={savingAi}
                className="inline-flex min-h-[44px] items-center gap-2 rounded-xl bg-indigo-600 px-6 py-2.5 text-xs font-bold text-white shadow-md hover:bg-indigo-500 disabled:opacity-50"
              >
                {savingAi ? "Đang lưu…" : "Lưu AI Profile"}
              </button>
            </div>
          </form>
        </Card>
      )}

      {/* ============================================================ */}
      {/* TAB 9: SETTINGS                                              */}
      {/* ============================================================ */}
      {activeTab === "settings" && (
        <Card className="p-5 sm:p-6">
          <form onSubmit={handleSaveSettings} className="space-y-4">
            <div className="border-b border-slate-100 pb-3">
              <h3 className="text-sm font-extrabold text-slate-900">Cài đặt Workspace (Kênh {channel.channel_title})</h3>
              <p className="text-xs text-slate-500">Thông tin kênh và các thông số vận hành</p>
            </div>

            {settingsSuccess && (
              <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs font-bold text-emerald-800">
                ✓ Đã lưu cài đặt thành công!
              </div>
            )}

            <div>
              <label className="text-xs font-bold text-slate-700">Tên Channel / Workspace</label>
              <input
                type="text"
                value={settingsName}
                onChange={(e) => setSettingsName(e.target.value)}
                className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm font-semibold text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none"
              />
            </div>

            <div>
              <label className="text-xs font-bold text-slate-700">YouTube Channel ID (Readonly)</label>
              <input
                type="text"
                readOnly
                value={channel.channel_id || "Chưa kết nối"}
                className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-2.5 font-mono text-xs text-slate-600 cursor-not-allowed"
              />
            </div>

            <div>
              <label className="text-xs font-bold text-slate-700">Daily Upload Limit</label>
              <input
                type="number"
                min={1}
                max={50}
                value={settingsLimit}
                onChange={(e) => setSettingsLimit(Number(e.target.value) || 1)}
                className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm font-semibold text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none"
              />
            </div>

            <div>
              <label className="text-xs font-bold text-slate-700">Quyền riêng tư mặc định (Default Privacy)</label>
              <select
                value={settingsPrivacy}
                onChange={(e) => setSettingsPrivacy(e.target.value)}
                className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-xs font-bold text-slate-700 shadow-sm"
              >
                <option value="public">Public</option>
                <option value="unlisted">Unlisted</option>
                <option value="private">Private</option>
              </select>
            </div>

            <div>
              <label className="text-xs font-bold text-slate-700">Timezone</label>
              <input
                type="text"
                value={settingsTz}
                onChange={(e) => setSettingsTz(e.target.value)}
                placeholder="Asia/Ho_Chi_Minh"
                className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm font-semibold text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none"
              />
            </div>

            <div>
              <label className="text-xs font-bold text-slate-700">Default publish mode (kênh này)</label>
              <select
                value={settingsPublishMode}
                onChange={(e) => setSettingsPublishMode(e.target.value)}
                className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-xs font-bold text-slate-700 shadow-sm"
              >
                <option value="immediate">Publish immediately</option>
                <option value="scheduled">Schedule</option>
                <option value="private">Private</option>
                <option value="unlisted">Unlisted</option>
              </select>
              <p className="mt-1 text-[11px] text-slate-500">
                Nếu chọn Schedule, cấu hình timezone + slots ở tab Auto. Upload sẽ private + publishAt native.
              </p>
            </div>

            {/* ============================================================ */}
            {/* SECTION A: AI METADATA (unchanged system prompt)              */}
            {/* ============================================================ */}
            <div className="rounded-2xl border border-slate-200 bg-slate-50/60 p-4">
              <div className="border-b border-slate-200 pb-2">
                <h4 className="text-xs font-extrabold uppercase tracking-wide text-slate-700">
                  AI Metadata
                </h4>
                <p className="text-[11px] text-slate-500">
                  Chỉ dùng cho tiêu đề, mô tả và hashtags khi upload video. Prompt này KHÔNG liên quan tới AI trả lời bình luận.
                </p>
              </div>
              <div className="mt-3">
                <label className="text-xs font-bold text-slate-700">
                  Metadata System Prompt
                </label>
                <textarea
                  rows={8}
                  value={aiPrompt}
                  onChange={(e) => setAiPrompt(e.target.value)}
                  placeholder="System Prompt cho việc tạo title / description / hashtags..."
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-white p-3 font-mono text-xs text-slate-800 shadow-sm focus:border-indigo-500 focus:outline-none"
                />
                <p className="mt-1 text-[11px] text-slate-400">
                  Có thể chỉnh chi tiết hơn ở tab AI Profile. Nút “Lưu thay đổi” bên dưới sẽ lưu cả prompt này.
                </p>
              </div>
            </div>

            {/* ============================================================ */}
            {/* SECTION B: AI COMMENT REPLY (fully separate prompt)          */}
            {/* ============================================================ */}
            <div className="rounded-2xl border border-indigo-200 bg-indigo-50/40 p-4">
              <div className="border-b border-indigo-100 pb-2">
                <h4 className="text-xs font-extrabold uppercase tracking-wide text-indigo-700">
                  AI Comment Reply
                </h4>
                <p className="text-[11px] text-slate-500">
                  Chỉ dùng để đọc bình luận và tạo câu trả lời. Prompt này hoàn toàn tách biệt với AI Metadata ở trên.
                </p>
              </div>

              {commentSettingsSuccess && (
                <div className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs font-bold text-emerald-800">
                  ✓ Đã lưu cài đặt AI Comment Reply!
                </div>
              )}

              <div className="mt-3 flex flex-wrap items-center gap-4">
                <label className="inline-flex items-center gap-2 text-xs font-bold text-slate-700">
                  <input
                    type="checkbox"
                    checked={crEnabled}
                    onChange={(e) => setCrEnabled(e.target.checked)}
                    className="h-4 w-4 rounded border-slate-300"
                  />
                  AI Comment Assistant
                </label>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold text-slate-700">Mode</span>
                  <select
                    value={crMode}
                    onChange={(e) => setCrMode(e.target.value as CommentReplyMode)}
                    className="rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs font-bold text-slate-700 shadow-sm"
                  >
                    <option value="off">OFF</option>
                    <option value="review">Manual Review</option>
                    <option value="auto">Auto Reply</option>
                  </select>
                </div>
              </div>

              <div className="mt-3">
                <label className="text-xs font-bold text-slate-700">
                  Comment Reply System Prompt
                </label>
                <textarea
                  rows={8}
                  value={crPrompt}
                  onChange={(e) => setCrPrompt(e.target.value)}
                  placeholder={
                    crDefaultPrompt ||
                    "Ví dụ: You are the community manager for this channel. Reply naturally, friendly, short and playful..."
                  }
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-white p-3 font-mono text-xs text-slate-800 shadow-sm focus:border-indigo-500 focus:outline-none"
                />
                <p className="mt-1 text-[11px] text-slate-400">
                  Để trống sẽ dùng đúng prompt mặc định của backend (nội dung xám trong ô trên) — prompt này
                  tách hoàn toàn khỏi AI Metadata.
                </p>
              </div>

              <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label className="text-xs font-bold text-slate-700">Reply language</label>
                  <select
                    value={crLanguage}
                    onChange={(e) => setCrLanguage(e.target.value)}
                    className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-bold text-slate-700 shadow-sm"
                  >
                    <option value="auto">AUTO (theo ngôn ngữ comment)</option>
                    <option value="en">English</option>
                    <option value="vi">Vietnamese</option>
                    <option value="zh">Chinese</option>
                    <option value="ko">Korean</option>
                    <option value="ja">Japanese</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs font-bold text-slate-700">Reply style</label>
                  <select
                    value={crStyle}
                    onChange={(e) => setCrStyle(e.target.value)}
                    className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-bold text-slate-700 shadow-sm"
                  >
                    <option value="friendly">Friendly</option>
                    <option value="funny">Funny</option>
                    <option value="warm">Warm</option>
                    <option value="short">Short</option>
                    <option value="professional">Professional</option>
                    <option value="custom">Custom (theo prompt)</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs font-bold text-slate-700">Max replies/day</label>
                  <input
                    type="number"
                    min={0}
                    max={500}
                    value={crDailyLimit}
                    onChange={(e) => setCrDailyLimit(Number(e.target.value) || 0)}
                    className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-bold text-slate-900 shadow-sm"
                  />
                </div>
                <div>
                  <label className="text-xs font-bold text-slate-700">Min interval (giây)</label>
                  <input
                    type="number"
                    min={0}
                    max={86400}
                    value={crMinInterval}
                    onChange={(e) => setCrMinInterval(Number(e.target.value) || 0)}
                    className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-bold text-slate-900 shadow-sm"
                  />
                </div>
              </div>

              <p className="mt-3 rounded-xl border border-indigo-100 bg-white/70 p-2 text-[11px] font-semibold text-slate-500">
                Bình luận khen/ngợi → AI viết 1 câu cảm ơn ngắn. Các loại khác → backend trả đúng 1 emoji,
                không gọi model: question 😊 · neutral ❤️ · negative 🙏 · funny 😂 · excited 🔥 · emoji-only ❤️.
              </p>

              <div className="mt-3 flex flex-wrap gap-4">
                {[
                  { label: "Reply only to new comments", value: crNewOnly, set: setCrNewOnly },
                  { label: "Reply to positive", value: crPositive, set: setCrPositive },
                  { label: "Reply to questions", value: crQuestions, set: setCrQuestions },
                  { label: "Reply to neutral", value: crNeutral, set: setCrNeutral },
                  { label: "Reply to negative", value: crNegative, set: setCrNegative },
                  { label: "Reply to emoji-only", value: crEmojiOnly, set: setCrEmojiOnly },
                  { label: "Reply to funny", value: crFunny, set: setCrFunny },
                  { label: "Reply to excited", value: crExcited, set: setCrExcited },
                ].map((f) => (
                  <label
                    key={f.label}
                    className="inline-flex items-center gap-2 text-[11px] font-bold text-slate-700"
                  >
                    <input
                      type="checkbox"
                      checked={f.value}
                      onChange={(e) => f.set(e.target.checked)}
                      className="h-4 w-4 rounded border-slate-300"
                    />
                    {f.label}
                  </label>
                ))}
              </div>

              <div className="mt-3">
                <button
                  type="button"
                  onClick={() => handleSaveCommentSettings()}
                  disabled={savingComment}
                  className="inline-flex min-h-[40px] items-center gap-2 rounded-xl bg-indigo-600 px-5 py-2 text-xs font-bold text-white shadow-sm hover:bg-indigo-500 disabled:opacity-50"
                >
                  {savingComment ? "Đang lưu…" : "Lưu AI Comment Reply"}
                </button>
              </div>
            </div>

            <div className="pt-3">
              <button
                type="submit"
                disabled={savingSettings}
                className="inline-flex min-h-[44px] items-center gap-2 rounded-xl bg-indigo-600 px-6 py-2.5 text-xs font-bold text-white shadow-md hover:bg-indigo-500 disabled:opacity-50"
              >
                {savingSettings ? "Đang lưu…" : "Lưu thay đổi"}
              </button>
            </div>
          </form>
        </Card>
      )}
    </div>
  );
}
