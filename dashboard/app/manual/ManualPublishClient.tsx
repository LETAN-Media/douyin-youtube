"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import Link from "next/link";
import { Badge, Card, PageHeader, ProgressBar } from "@/components/ui";
import {
  IconAlert,
  IconPlus,
  IconRefresh,
  IconSparkles,
  IconUpload,
  IconX,
} from "@/components/icons";
import type {
  Destination,
  ManualMetadataResult,
  ManualPublicationItem,
  ManualPublishPayload,
  ManualPublishResponse,
  ManualResolveResult,
} from "@/lib/types";
import { platformLabel } from "@/lib/format";
import { YouTubePublishSelector } from "@/components/YouTubePublishSelector";

function formatDuration(sec?: number | null): string {
  if (sec == null || sec <= 0) return "00:00";
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

interface ManualPublishClientProps {
  initialDestinations: Destination[];
  initialHistory: ManualPublicationItem[];
}

export function ManualPublishClient({
  initialDestinations,
  initialHistory,
}: ManualPublishClientProps) {
  // Input & Parse state
  const [input, setInput] = useState("");
  const [resolving, setResolving] = useState(false);
  const [resolveError, setResolveError] = useState<string | null>(null);
  const [resolvedVideo, setResolvedVideo] = useState<ManualResolveResult | null>(null);
  const [profileDetected, setProfileDetected] = useState<ManualResolveResult | null>(null);

  // Destinations state
  const [destinations, setDestinations] = useState<Destination[]>(initialDestinations);
  const [loadingDestinations, setLoadingDestinations] = useState(false);
  const [selectedDestinations, setSelectedDestinations] = useState<string[]>(() => {
    const firstConnected = initialDestinations.find(
      (d) => d.platform === "youtube" && d.connected && d.enabled,
    );
    return firstConnected ? [firstConnected.id] : [];
  });
  const [activeDestSubTab, setActiveDestSubTab] = useState<string>(() => {
    const firstConnected = initialDestinations.find(
      (d) => d.platform === "youtube" && d.connected && d.enabled,
    );
    return firstConnected ? firstConnected.id : "";
  });

  // Publish settings (native YouTube scheduling)
  const [privacy, setPrivacy] = useState<"public" | "unlisted" | "private">("public");
  const [publishMode, setPublishMode] = useState<"immediate" | "scheduled" | "private" | "unlisted">("immediate");
  const [schedDate, setSchedDate] = useState("");
  const [schedTime, setSchedTime] = useState("");
  const [schedTz, setSchedTz] = useState("Asia/Ho_Chi_Minh");
  const [generateAi, setGenerateAi] = useState(true);
  const [metadataMode, setMetadataMode] = useState<"same" | "separate">("same");

  // Metadata form state (same mode)
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [hashtags, setHashtags] = useState("");
  const [coreHashtags, setCoreHashtags] = useState<string[]>([]);
  const [dynamicHashtags, setDynamicHashtags] = useState<string[]>([]);

  // Metadata form state (separate mode: by dest id)
  const [separateMetadata, setSeparateMetadata] = useState<
    Record<string, { title: string; description: string; hashtags: string }>
  >({});

  const [generatingMetadata, setGeneratingMetadata] = useState(false);
  const [metadataError, setMetadataError] = useState<string | null>(null);

  // Publishing & Progress state
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);
  const [duplicateWarning, setDuplicateWarning] = useState<{
    message: string;
    destination_id: string;
    destination_name: string;
    external_url?: string;
  } | null>(null);
  const [limitModal, setLimitModal] = useState<{
    destination_id: string;
    destination_name: string;
    daily_limit: number;
    published_today: number;
  } | null>(null);

  const [activePublications, setActivePublications] = useState<ManualPublicationItem[]>([]);
  const [history, setHistory] = useState<ManualPublicationItem[]>(initialHistory);
  const [loadingHistory, setLoadingHistory] = useState(false);

  // Load all destinations
  const loadDestinations = useCallback(async () => {
    try {
      setLoadingDestinations(true);
      const res = await fetch("/api/manual/destinations");
      if (!res.ok) throw new Error("Không tải được destinations");
      const data: Destination[] = await res.json();
      setDestinations(data);
      const firstConnected = data.find(
        (d) => d.platform === "youtube" && d.connected && d.enabled,
      );
      if (firstConnected) {
        setSelectedDestinations((prev) => (prev.length === 0 ? [firstConnected.id] : prev));
        setActiveDestSubTab((prev) => (prev ? prev : firstConnected.id));
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoadingDestinations(false);
    }
  }, []);

  // Load manual history
  const loadHistory = useCallback(async () => {
    try {
      setLoadingHistory(true);
      const res = await fetch("/api/manual/publications?limit=30");
      if (!res.ok) return;
      const data: ManualPublicationItem[] = await res.json();
      setHistory(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoadingHistory(false);
    }
  }, []);

  // Generate metadata helper
  const triggerAiMetadata = useCallback(
    async (
      sourceUrl: string,
      captionText: string,
      destIds: string[],
      mode: "same" | "separate",
    ) => {
      setGeneratingMetadata(true);
      setMetadataError(null);
      try {
        const res = await fetch("/api/manual/metadata", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            source_url: sourceUrl,
            caption: captionText,
            destination_ids: destIds,
            metadata_mode: mode,
          }),
        });

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.error || "Tạo metadata thất bại");
        }

        const data: ManualMetadataResult = await res.json();
        if (data.metadata_mode === "separate" && data.by_destination) {
          const map: Record<string, { title: string; description: string; hashtags: string }> = {};
          for (const [did, item] of Object.entries(data.by_destination)) {
            map[did] = {
              title: item.title,
              description: item.description,
              hashtags: item.hashtags.join(" "),
            };
          }
          setSeparateMetadata(map);
        } else if (data.same) {
          setTitle(data.same.title);
          setDescription(data.same.description);
          setHashtags(data.same.hashtags.join(" "));
          setCoreHashtags(data.same.core_hashtags ?? []);
          setDynamicHashtags(data.same.dynamic_hashtags ?? []);
        }
      } catch (err: unknown) {
        setMetadataError(err instanceof Error ? err.message : "Tạo metadata AI thất bại");
      } finally {
        setGeneratingMetadata(false);
      }
    },
    [],
  );

  // Handle URL parse
  const handleResolve = async () => {
    const raw = input.trim();
    if (!raw || resolving) return;

    setResolving(true);
    setResolveError(null);
    setProfileDetected(null);
    setResolvedVideo(null);

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

      // Initialize title & description from Douyin metadata
      const initialCaption = data.caption || "";
      setTitle(initialCaption.slice(0, 80));
      setDescription(initialCaption);
      setHashtags("#shorts #trending #viral #video #fyp");

      // Auto trigger AI metadata if enabled
      if (generateAi) {
        triggerAiMetadata(
          data.source_url,
          initialCaption,
          selectedDestinations,
          metadataMode,
        );
      }
    } catch (err: unknown) {
      setResolveError(err instanceof Error ? err.message : "Không nhận diện được link");
    } finally {
      setResolving(false);
    }
  };

  // Toggle destination selection
  const handleToggleDest = (destId: string) => {
    setSelectedDestinations((prev) => {
      const exists = prev.includes(destId);
      const next = exists ? prev.filter((id) => id !== destId) : [...prev, destId];
      if (!exists && !activeDestSubTab) {
        setActiveDestSubTab(destId);
      } else if (exists && activeDestSubTab === destId) {
        setActiveDestSubTab(next[0] || "");
      }
      return next;
    });
  };

  // Switch metadata mode
  const handleMetadataModeChange = (newMode: "same" | "separate") => {
    setMetadataMode(newMode);
    if (resolvedVideo && generateAi) {
      triggerAiMetadata(
        resolvedVideo.source_url,
        resolvedVideo.caption || "",
        selectedDestinations,
        newMode,
      );
    }
  };

  // Reset metadata
  const handleResetMetadata = () => {
    if (!resolvedVideo) return;
    const initialCaption = resolvedVideo.caption || "";
    setTitle(initialCaption.slice(0, 80));
    setDescription(initialCaption);
    setHashtags("#shorts #trending #viral #video #fyp");
    if (metadataMode === "separate") {
      const resetMap: Record<string, { title: string; description: string; hashtags: string }> = {};
      for (const did of selectedDestinations) {
        resetMap[did] = {
          title: initialCaption.slice(0, 80),
          description: initialCaption,
          hashtags: "#shorts #trending #viral #video #fyp",
        };
      }
      setSeparateMetadata(resetMap);
    }
  };

  // Regenerate AI
  const handleRegenerateAi = () => {
    if (!resolvedVideo) return;
    triggerAiMetadata(
      resolvedVideo.source_url,
      resolvedVideo.caption || "",
      selectedDestinations,
      metadataMode,
    );
  };

  // Publish Now
  const handlePublish = async (forceDuplicate = false, queueIfFull = false) => {
    if (!resolvedVideo || selectedDestinations.length === 0 || publishing) return;

    setPublishing(true);
    setPublishError(null);
    setDuplicateWarning(null);

    try {
      // Build destinations_metadata if separate
      const destMetaPayload: Record<string, { title: string; description: string }> = {};
      if (metadataMode === "separate") {
        for (const did of selectedDestinations) {
          const item = separateMetadata[did];
          const fullDesc = item
            ? `${item.description}\n\n${item.hashtags}`.trim()
            : `${description}\n\n${hashtags}`.trim();
          destMetaPayload[did] = {
            title: item?.title || title || resolvedVideo.caption || "",
            description: fullDesc,
          };
        }
      }

      const fullSameDesc = `${description}\n\n${hashtags}`.trim();

      const effMode = publishMode;
      const effPrivacy = effMode === "immediate" ? "public" : effMode === "scheduled" ? "private" : effMode;
      const payload: ManualPublishPayload = {
        source_url: resolvedVideo.source_url,
        source_title: resolvedVideo.caption || resolvedVideo.video_id || "Douyin Video",
        video_id: resolvedVideo.video_id,
        thumbnail: resolvedVideo.thumbnail,
        duration: resolvedVideo.duration,
        destination_ids: selectedDestinations,
        metadata_mode: metadataMode,
        title: title || resolvedVideo.caption || "",
        description: fullSameDesc,
        destinations_metadata: destMetaPayload,
        privacy_status: effPrivacy as "public" | "unlisted" | "private",
        force_duplicate: forceDuplicate,
        youtube_publish_mode: effMode,
        youtube_publish_date: effMode === "scheduled" && schedDate ? schedDate : undefined,
        youtube_publish_time: effMode === "scheduled" && schedTime ? schedTime : undefined,
        youtube_schedule_timezone: schedTz,
        queue_if_full: queueIfFull,
      };

      const res = await fetch("/api/manual/publish", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await res.json();

      const isDailyLimit =
        data.code === "DAILY_LIMIT_REACHED" ||
        data.override_required === true ||
        (data.detail && typeof data.detail === "object" && (data.detail.code === "DAILY_LIMIT_REACHED" || data.detail.override_required === true));

      if (res.status === 409 && isDailyLimit) {
        const detailObj = (data.detail && typeof data.detail === "object" ? data.detail : data) as Record<string, unknown>;
        setLimitModal({
          destination_id: String(detailObj.destination_id || selectedDestinations[0] || ""),
          destination_name: String(detailObj.destination_name || "YouTube Channel"),
          daily_limit: Number(detailObj.daily_limit || 4),
          published_today: Number(detailObj.published_today || 4),
        });
        return;
      }

      if (res.status === 409 && data.code === "DUPLICATE_VIDEO") {
        setDuplicateWarning({
          message: data.message || "Video này đã được đăng lên kênh.",
          destination_id: data.destination_id,
          destination_name: data.destination_name,
          external_url: data.external_url,
        });
        return;
      }

      if (!res.ok) {
        throw new Error(data.error || data.detail || "Đăng video thất bại");
      }

      const result: ManualPublishResponse = data;
      if (result.publications && result.publications.length > 0) {
        setActivePublications((prev) => [...result.publications, ...prev]);
        loadHistory();
      }
    } catch (err: unknown) {
      setPublishError(err instanceof Error ? err.message : "Đăng video thất bại");
    } finally {
      setPublishing(false);
    }
  };

  const handleCancelLimit = async () => {
    setLimitModal(null);
    await handlePublish(false, true);
  };

  const handleConfirmOverride = async () => {
    if (!limitModal) return;
    const destId = limitModal.destination_id;
    setLimitModal(null);
    setPublishing(true);
    try {
      await fetch(`/api/channels/${encodeURIComponent(destId)}/overrides`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          extra_allowed: 1,
          reason: "User confirmed override via UI",
          source: "ui_confirmation",
        }),
      });
      await handlePublish(false, false);
    } catch (err: unknown) {
      setPublishError(err instanceof Error ? err.message : "Tạo override thất bại");
      setPublishing(false);
    }
  };

  // Polling for active publications
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
          loadHistory();
        }
      } catch (e) {
        console.error("Poll error:", e);
      }
    }, 2000);

    return () => {
      if (pollActiveRef.current) clearInterval(pollActiveRef.current);
    };
  }, [activePublications, loadHistory]);

  // Handle Retry
  const handleRetry = async (pubId: string) => {
    try {
      const res = await fetch(`/api/manual/publications/${pubId}/retry`, {
        method: "POST",
      });
      if (!res.ok) throw new Error("Retry thất bại");
      const updatedPub: ManualPublicationItem = await res.json();
      setActivePublications((prev) => [
        updatedPub,
        ...prev.filter((p) => p.id !== pubId),
      ]);
      loadHistory();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Retry thất bại");
    }
  };

  // Destination stats
  const activeDestinations = destinations.filter((d) => d.platform === "youtube");
  const facebookDestinations = destinations.filter((d) => d.platform === "facebook");

  return (
    <>
      <PageHeader
        eyebrow="Direct Publishing"
        title="Manual Publish"
        description="Dán link Douyin để đăng ngay lên YouTube / Facebook không cần qua Inventory hay Scheduler."
        actions={
          <div className="flex items-center gap-2">
            <Link
              href="/"
              className="inline-flex min-h-[44px] items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50"
            >
              ← Auto Dashboard
            </Link>
          </div>
        }
      />

      {/* Mode Switcher */}
      <div className="mt-4 flex items-center gap-2 border-b border-slate-200/80 pb-3">
        <div className="inline-flex rounded-xl bg-slate-100 p-1">
          <Link
            href="/"
            className="inline-flex items-center gap-1.5 rounded-lg px-3.5 py-1.5 text-xs font-semibold text-slate-600 transition hover:text-slate-900"
          >
            Auto Mode
          </Link>
          <span className="inline-flex items-center gap-1.5 rounded-lg bg-white px-3.5 py-1.5 text-xs font-extrabold text-indigo-700 shadow-sm">
            <IconUpload size={14} />
            Manual Publish
          </span>
        </div>
      </div>

      {/* Main Container */}
      <div className="mt-6 space-y-6">
        {/* Step 1: Input Douyin URL / Share Text */}
        <Card className="p-5 sm:p-6">
          <div className="flex flex-col gap-2">
            <label
              htmlFor="douyin-input"
              className="text-sm font-extrabold text-slate-900"
            >
              1. Dán link Douyin hoặc toàn bộ nội dung chia sẻ
            </label>
            <p className="text-xs text-slate-500">
              Chấp nhận short link <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-slate-700">v.douyin.com/...</code>, video link trực tiếp, hoặc share text đầy đủ. Nhấn <kbd className="rounded border border-slate-200 bg-slate-100 px-1.5 py-0.5 font-mono text-xs font-semibold text-slate-700">Enter</kbd> để tự động nhận diện.
            </p>

            <div className="mt-2 flex flex-col gap-2.5 sm:flex-row">
              <div className="relative flex-1">
                <input
                  id="douyin-input"
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      handleResolve();
                    }
                  }}
                  placeholder="Dán https://v.douyin.com/xxxx/ hoặc 复制打开抖音..."
                  className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 placeholder-slate-400 shadow-sm transition focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
                />
                {input ? (
                  <button
                    type="button"
                    onClick={() => setInput("")}
                    className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md p-1 text-slate-400 hover:text-slate-600"
                  >
                    <IconX size={16} />
                  </button>
                ) : null}
              </div>

              <button
                type="button"
                onClick={handleResolve}
                disabled={resolving || !input.trim()}
                className="inline-flex min-h-[46px] items-center justify-center gap-2 rounded-xl bg-indigo-600 px-6 py-3 text-sm font-bold text-white shadow-[0_4px_12px_-4px_rgba(79,70,229,0.5)] transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {resolving ? (
                  <>
                    <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                    Đang nhận diện…
                  </>
                ) : (
                  <>
                    <IconUpload size={16} />
                    Parse & Preview
                  </>
                )}
              </button>
            </div>

            {resolveError ? (
              <p className="mt-2 flex items-center gap-1.5 text-xs font-semibold text-rose-600">
                <IconAlert size={14} />
                {resolveError}
              </p>
            ) : null}
          </div>
        </Card>

        {/* Profile Link Detection Warning (Requirement 9) */}
        {profileDetected ? (
          <Card className="border-amber-300 bg-amber-50/70 p-5 sm:p-6">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-start gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-amber-100 text-amber-700">
                  <IconAlert size={20} />
                </span>
                <div>
                  <p className="text-sm font-extrabold text-amber-900">
                    This is a Douyin profile, not a single video.
                  </p>
                  <p className="mt-0.5 text-xs text-amber-700">
                    Manual Publish chỉ đăng từng video đơn lẻ. Để tự động quét toàn bộ kênh này vào Inventory, vui lòng thêm Profile vào Auto Sources.
                  </p>
                  {profileDetected.profile_url ? (
                    <p className="mt-1 font-mono text-[11px] text-amber-800 break-all">
                      {profileDetected.profile_url}
                    </p>
                  ) : null}
                </div>
              </div>

              <div className="flex items-center gap-2 pt-2 sm:pt-0">
                <Link
                  href="/"
                  className="inline-flex min-h-[40px] items-center gap-1.5 rounded-xl border border-amber-300 bg-white px-3.5 py-2 text-xs font-bold text-amber-900 shadow-sm transition hover:bg-amber-50"
                >
                  <IconPlus size={14} />
                  Add as Auto Source
                </Link>
                <Link
                  href="/"
                  className="inline-flex min-h-[40px] items-center gap-1.5 rounded-xl bg-amber-600 px-3.5 py-2 text-xs font-bold text-white shadow-sm transition hover:bg-amber-500"
                >
                  View Inventory
                </Link>
              </div>
            </div>
          </Card>
        ) : null}

        {/* Step 2: Video Preview (Requirement 2) */}
        {resolvedVideo ? (
          <Card className="overflow-hidden border-slate-200/90 p-5 sm:p-6">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h2 className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
                2. Preview Video
              </h2>
              <Badge tone="green" dot>
                {resolvedVideo.status || "Video detected"}
              </Badge>
            </div>

            <div className="mt-4 flex flex-col gap-4 sm:flex-row sm:items-start sm:gap-6">
              {/* Thumbnail */}
              <div className="relative aspect-[9/16] w-full max-w-[160px] shrink-0 overflow-hidden rounded-xl bg-slate-900 shadow-sm sm:w-40">
                {resolvedVideo.thumbnail ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={resolvedVideo.thumbnail}
                    alt={resolvedVideo.caption || "Thumbnail"}
                    className="h-full w-full object-cover"
                  />
                ) : (
                  <div className="flex h-full w-full items-center justify-center text-xs text-slate-500">
                    No preview
                  </div>
                )}
                {resolvedVideo.duration ? (
                  <span className="absolute bottom-2 right-2 rounded-md bg-black/80 px-1.5 py-0.5 font-mono text-[10px] font-extrabold text-white backdrop-blur">
                    {formatDuration(resolvedVideo.duration)}
                  </span>
                ) : null}
              </div>

              {/* Metadata details */}
              <div className="flex-1 space-y-2.5">
                <div className="flex items-center gap-2">
                  <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-indigo-100 text-xs font-bold text-indigo-700">
                    {(resolvedVideo.author || "D")[0]}
                  </span>
                  <p className="text-sm font-bold text-slate-900">
                    {resolvedVideo.author || "Douyin Creator"}
                  </p>
                </div>

                <p className="text-sm font-medium text-slate-800 leading-relaxed">
                  {resolvedVideo.caption || "Không có caption"}
                </p>

                <div className="flex flex-wrap items-center gap-4 text-xs text-slate-500 pt-1">
                  <span>
                    Duration: <strong className="text-slate-800">{formatDuration(resolvedVideo.duration)}</strong>
                  </span>
                  {resolvedVideo.video_id ? (
                    <span>
                      Video ID: <code className="font-mono text-slate-700">{resolvedVideo.video_id}</code>
                    </span>
                  ) : null}
                </div>

                <div className="pt-2">
                  <a
                    href={resolvedVideo.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs font-semibold text-indigo-600 hover:text-indigo-800 hover:underline"
                  >
                    Mở link Douyin gốc ↗
                  </a>
                </div>
              </div>
            </div>
          </Card>
        ) : null}

        {/* Step 3: Destination Selection & Privacy (Requirement 3, 4, 13, 17) */}
        {resolvedVideo ? (
          <Card className="p-5 sm:p-6">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-3">
              <div>
                <h2 className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
                  3. Chọn kênh để đăng
                </h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  Có thể chọn 1 hoặc nhiều kênh. Mỗi kênh YouTube được chọn sẽ tạo 1 Publication riêng biệt.
                </p>
              </div>

              {/* Privacy kept for compat; native mode selector below */}
              <div className="flex items-center gap-1.5 rounded-xl border border-slate-200 bg-slate-50 p-1">
                <span className="px-2 text-xs font-semibold text-slate-500">Privacy:</span>
                {(["public", "unlisted", "private"] as const).map((p) => (
                  <button
                    key={p}
                    type="button"
                    onClick={() => {
                      setPrivacy(p);
                      setPublishMode(p === "public" ? "immediate" : p);
                    }}
                    className={`rounded-lg px-2.5 py-1 text-xs font-bold capitalize transition ${
                      (publishMode === "immediate" ? "public" : publishMode) === p
                        ? "bg-white text-indigo-700 shadow-sm"
                        : "text-slate-600 hover:text-slate-900"
                    }`}
                  >
                    {p}
                  </button>
                ))}
              </div>
            </div>

            {loadingDestinations ? (
              <div className="flex items-center justify-center py-8 text-xs text-slate-400">
                Đang tải danh sách destination…
              </div>
            ) : destinations.length === 0 ? (
              <div className="py-6 text-center text-xs text-slate-500">
                Chưa có destination nào. Vui lòng thêm destination trong pipeline.
              </div>
            ) : (
              <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {/* YouTube Channels */}
                {activeDestinations.map((d) => {
                  const isConnected = d.connected;
                  const isSelected = selectedDestinations.includes(d.id);
                  return (
                    <div
                      key={d.id}
                      className={`relative flex flex-col justify-between rounded-2xl border p-4 transition ${
                        !isConnected
                          ? "border-slate-200/70 bg-slate-50/60 opacity-80"
                          : isSelected
                            ? "border-indigo-500 bg-indigo-50/40 ring-2 ring-indigo-500/20"
                            : "border-slate-200/90 bg-white hover:border-slate-300"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <label className="flex items-start gap-3 cursor-pointer select-none">
                          <input
                            type="checkbox"
                            checked={isSelected}
                            disabled={!isConnected}
                            onChange={() => handleToggleDest(d.id)}
                            className="mt-0.5 h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 disabled:opacity-40"
                          />
                          <div className="min-w-0">
                            <div className="flex items-center gap-1.5">
                              <span className="flex h-5 w-5 items-center justify-center rounded bg-red-600 text-[10px] font-black text-white">
                                YT
                              </span>
                              <p className="truncate text-sm font-extrabold text-slate-900">
                                {d.name}
                              </p>
                            </div>
                            <p className="text-xs text-slate-500 mt-0.5">
                              {d.external_account_name || "YouTube Channel"}
                            </p>
                          </div>
                        </label>

                        {isConnected ? (
                          <Badge tone="green" dot>Connected</Badge>
                        ) : (
                          <span className="rounded-full bg-slate-200 px-2 py-0.5 text-[10px] font-bold text-slate-600">
                            Not Connected
                          </span>
                        )}
                      </div>

                      <div className="mt-3 flex items-center justify-between border-t border-slate-100 pt-2 text-[11px] text-slate-400">
                        <span>{d.enabled ? "Active" : "Paused"}</span>
                        {!isConnected ? (
                          <a
                            href={`/api/youtube/oauth-url?destination_id=${d.id}`}
                            className="font-bold text-indigo-600 hover:underline"
                          >
                            [ Connect ]
                          </a>
                        ) : (
                          <span className="text-emerald-600 font-semibold">Sẵn sàng</span>
                        )}
                      </div>
                    </div>
                  );
                })}

                {/* Facebook Channels (Unsupported badge) */}
                {facebookDestinations.map((d) => (
                  <div
                    key={d.id}
                    className="relative flex flex-col justify-between rounded-2xl border border-slate-200/70 bg-slate-50/60 p-4 opacity-70"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-start gap-3">
                        <input
                          type="checkbox"
                          disabled
                          className="mt-0.5 h-4 w-4 rounded border-slate-300 opacity-40 cursor-not-allowed"
                        />
                        <div>
                          <div className="flex items-center gap-1.5">
                            <span className="flex h-5 w-5 items-center justify-center rounded bg-blue-600 text-[10px] font-black text-white">
                              FB
                            </span>
                            <p className="truncate text-sm font-bold text-slate-700">
                              {d.name}
                            </p>
                          </div>
                          <p className="text-xs text-slate-400 mt-0.5">Facebook Page</p>
                        </div>
                      </div>
                      <span className="rounded-full bg-slate-200 px-2 py-0.5 text-[10px] font-bold text-slate-600">
                        Not Available
                      </span>
                    </div>

                    <div className="mt-3 border-t border-slate-100 pt-2 text-[11px] text-amber-700">
                      Publisher adapter chưa được cấu hình
                    </div>
                  </div>
                ))}
              </div>
            )}
            <div className="mt-4">
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
          </Card>
        ) : null}

        {/* Step 4: AI Metadata & Preview (Requirement 5, 6, 7) */}
        {resolvedVideo ? (
          <Card className="p-5 sm:p-6">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 pb-3">
              <div className="flex items-center gap-3">
                <h2 className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
                  4. Metadata & Nội dung
                </h2>
                <label className="flex items-center gap-1.5 text-xs font-bold text-indigo-700 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={generateAi}
                    onChange={(e) => setGenerateAi(e.target.checked)}
                    className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                  />
                  <IconSparkles size={14} />
                  Generate metadata with AI
                </label>
              </div>

              {/* Multi-destination metadata mode (Requirement 7) */}
              {selectedDestinations.length > 1 ? (
                <div className="flex items-center gap-3 text-xs font-medium text-slate-600">
                  <span>Metadata mode:</span>
                  <label className="flex items-center gap-1 cursor-pointer">
                    <input
                      type="radio"
                      name="meta-mode"
                      checked={metadataMode === "same"}
                      onChange={() => handleMetadataModeChange("same")}
                      className="text-indigo-600"
                    />
                    Same metadata for all
                  </label>
                  <label className="flex items-center gap-1 cursor-pointer">
                    <input
                      type="radio"
                      name="meta-mode"
                      checked={metadataMode === "separate"}
                      onChange={() => handleMetadataModeChange("separate")}
                      className="text-indigo-600"
                    />
                    Generate separately per destination
                  </label>
                </div>
              ) : null}
            </div>

            {/* Separate Mode Destination Tabs */}
            {metadataMode === "separate" && selectedDestinations.length > 1 ? (
              <div className="mt-4 flex items-center gap-2 border-b border-slate-200 pb-2 overflow-x-auto">
                {selectedDestinations.map((did) => {
                  const d = destinations.find((x) => x.id === did);
                  const active = activeDestSubTab === did;
                  return (
                    <button
                      key={did}
                      type="button"
                      onClick={() => setActiveDestSubTab(did)}
                      className={`whitespace-nowrap rounded-xl px-3 py-1.5 text-xs font-bold transition ${
                        active
                          ? "bg-indigo-600 text-white shadow-sm"
                          : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                      }`}
                    >
                      {d?.name || did}
                    </button>
                  );
                })}
              </div>
            ) : null}

            {/* Metadata Fields Form */}
            <div className="mt-4 space-y-4">
              {metadataError ? (
                <p className="rounded-xl border border-rose-200 bg-rose-50 p-2.5 text-xs font-semibold text-rose-700">
                  {metadataError}
                </p>
              ) : null}

              {generatingMetadata ? (
                <div className="flex items-center gap-2 text-xs font-bold text-indigo-600 py-3">
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-indigo-600 border-t-transparent" />
                  Đang sinh metadata AI chuẩn xác (Title, Description, 5 Hashtags)…
                </div>
              ) : null}

              {/* Editable Fields for Active Mode */}
              {metadataMode === "separate" && activeDestSubTab ? (
                <SeparateFields
                  destinationId={activeDestSubTab}
                  data={
                    separateMetadata[activeDestSubTab] || {
                      title,
                      description,
                      hashtags,
                    }
                  }
                  onChange={(field, val) => {
                    setSeparateMetadata((prev) => ({
                      ...prev,
                      [activeDestSubTab]: {
                        ...(prev[activeDestSubTab] || { title, description, hashtags }),
                        [field]: val,
                      },
                    }));
                  }}
                />
              ) : (
                <div className="space-y-4">
                  <div>
                    <label className="text-xs font-bold text-slate-700">Title</label>
                    <input
                      type="text"
                      value={title}
                      onChange={(e) => setTitle(e.target.value)}
                      placeholder="YouTube Video Title..."
                      className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm font-semibold text-slate-900 shadow-sm transition focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
                    />
                  </div>

                  <div>
                    <label className="text-xs font-bold text-slate-700">Description</label>
                    <textarea
                      rows={3}
                      value={description}
                      onChange={(e) => setDescription(e.target.value)}
                      placeholder="Mô tả nội dung video..."
                      className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-900 shadow-sm transition focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
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
                    <label className="text-xs font-bold text-slate-700">Hashtags (Exactly 5)</label>
                    <input
                      type="text"
                      value={hashtags}
                      onChange={(e) => setHashtags(e.target.value)}
                      placeholder="#tag1 #tag2 #tag3 #tag4 #tag5"
                      className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 font-mono text-sm font-bold text-indigo-600 shadow-sm transition focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
                    />
                  </div>
                </div>
              )}

              {/* Action Buttons */}
              <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-4">
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={handleRegenerateAi}
                    disabled={generatingMetadata}
                    className="inline-flex min-h-[38px] items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs font-bold text-slate-700 shadow-sm transition hover:bg-slate-50"
                  >
                    <IconRefresh size={14} />
                    Regenerate AI
                  </button>
                  <button
                    type="button"
                    onClick={handleResetMetadata}
                    className="inline-flex min-h-[38px] items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs font-bold text-slate-500 shadow-sm transition hover:bg-slate-50"
                  >
                    Reset
                  </button>
                </div>

                {/* Prominent Publish Now Button */}
                <button
                  type="button"
                  onClick={() => handlePublish(false)}
                  disabled={publishing || selectedDestinations.length === 0}
                  className="inline-flex min-h-[46px] items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-indigo-600 to-indigo-700 px-7 py-2.5 text-sm font-extrabold text-white shadow-[0_4px_16px_-4px_rgba(79,70,229,0.7)] transition hover:from-indigo-500 hover:to-indigo-600 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {publishing ? (
                    <>
                      <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                      Đang tạo job…
                    </>
                  ) : (
                    <>
                      <IconUpload size={17} />
                      Publish Now ({selectedDestinations.length} kênh)
                    </>
                  )}
                </button>
              </div>

              {publishError ? (
                <p className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs font-semibold text-rose-700">
                  {publishError}
                </p>
              ) : null}
            </div>
          </Card>
        ) : null}

        {/* Duplicate Warning Modal / Banner (Requirement 16) */}
        {duplicateWarning ? (
          <div className="rounded-2xl border border-amber-300 bg-amber-50 p-5 shadow-md">
            <div className="flex items-start gap-3">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-amber-200 text-amber-800">
                <IconAlert size={18} />
              </span>
              <div className="flex-1">
                <p className="text-sm font-extrabold text-amber-900">
                  {duplicateWarning.message}
                </p>
                <p className="mt-1 text-xs text-amber-700">
                  Video này đã được đăng thành công lên destination này trước đó. Bạn có muốn đăng lại (Publish Again) hay Hủy?
                </p>
                {duplicateWarning.external_url ? (
                  <p className="mt-1 text-xs">
                    <a
                      href={duplicateWarning.external_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-bold text-amber-800 underline"
                    >
                      Xem video đã đăng trên YouTube ↗
                    </a>
                  </p>
                ) : null}

                <div className="mt-4 flex items-center gap-3">
                  <button
                    type="button"
                    onClick={() => setDuplicateWarning(null)}
                    className="rounded-xl border border-slate-300 bg-white px-4 py-2 text-xs font-bold text-slate-700 shadow-sm hover:bg-slate-50"
                  >
                    Cancel (Mặc định)
                  </button>
                  <button
                    type="button"
                    onClick={() => handlePublish(true)}
                    className="rounded-xl bg-amber-600 px-4 py-2 text-xs font-bold text-white shadow-sm hover:bg-amber-500"
                  >
                    Publish Again
                  </button>
                </div>
              </div>
            </div>
          </div>
        ) : null}

        {/* Daily Shorts Limit Confirmation Modal */}
        {limitModal && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4 backdrop-blur-sm">
            <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl border border-slate-200">
              <div className="flex items-center gap-3 text-rose-600">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-rose-100 text-rose-600">
                  <IconAlert size={20} />
                </span>
                <div>
                  <h3 className="text-base font-extrabold text-slate-900">
                    Đạt giới hạn Shorts hôm nay
                  </h3>
                  <p className="text-xs text-slate-500">
                    {limitModal.destination_name}
                  </p>
                </div>
              </div>
              <p className="mt-4 text-sm text-slate-600 leading-relaxed">
                Channel này đã đạt giới hạn {limitModal.daily_limit} Shorts hôm nay.
              </p>
              <p className="mt-2 text-sm text-slate-700 font-semibold">
                Bạn có muốn vượt giới hạn và đăng thêm video này hôm nay không?
              </p>
              <div className="mt-6 flex items-center justify-end gap-3">
                <button
                  type="button"
                  onClick={handleCancelLimit}
                  className="rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-xs font-bold text-slate-700 hover:bg-slate-50 transition"
                >
                  Huỷ
                </button>
                <button
                  type="button"
                  onClick={handleConfirmOverride}
                  className="rounded-xl bg-rose-600 px-5 py-2.5 text-xs font-bold text-white shadow-sm hover:bg-rose-500 transition"
                >
                  Vẫn đăng
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Step 5: Live Progress (Requirement 12) */}
        {activePublications.length > 0 ? (
          <Card className="p-5 sm:p-6 border-indigo-200 bg-indigo-50/20">
            <div className="flex items-center justify-between border-b border-indigo-100 pb-3">
              <h2 className="text-xs font-extrabold uppercase tracking-wider text-indigo-900 flex items-center gap-2">
                <span className="relative flex h-2 w-2">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-indigo-400 opacity-75" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-indigo-500" />
                </span>
                Tiến độ đăng bài (Live Progress)
              </h2>
              <span className="text-xs font-semibold text-slate-500">
                {activePublications.filter((p) => p.status === "published").length}/
                {activePublications.length} hoàn tất
              </span>
            </div>

            <div className="mt-4 space-y-3">
              {activePublications.map((pub) => {
                const isPublished = pub.status === "published";
                const isFailed = pub.status === "failed";
                return (
                  <div
                    key={pub.id}
                    className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="flex h-6 w-6 items-center justify-center rounded bg-red-600 text-[10px] font-black text-white">
                          YT
                        </span>
                        <p className="text-sm font-bold text-slate-900">
                          {pub.destination_name}
                        </p>
                        <span className="text-xs text-slate-400">· {pub.video_title}</span>
                      </div>

                      <div className="flex items-center gap-2">
                        {isPublished ? (
                          <Badge tone="green" dot>Published</Badge>
                        ) : isFailed ? (
                          <Badge tone="rose" dot>Failed</Badge>
                        ) : (
                          <Badge tone="blue" dot>{pub.status}</Badge>
                        )}

                        {isFailed ? (
                          <button
                            type="button"
                            onClick={() => handleRetry(pub.id)}
                            className="rounded-lg bg-rose-50 border border-rose-200 px-2.5 py-1 text-xs font-bold text-rose-700 hover:bg-rose-100"
                          >
                            Retry
                          </button>
                        ) : null}
                      </div>
                    </div>

                    {/* Progress indicator */}
                    {!isPublished && !isFailed ? (
                      <div className="mt-3">
                        <div className="flex items-center justify-between text-xs text-slate-500 mb-1">
                          <span className="capitalize">{pub.status}…</span>
                          <span>{pub.progress}%</span>
                        </div>
                        <ProgressBar
                          value={pub.progress || 20}
                          tone="indigo"
                        />
                      </div>
                    ) : null}

                    {/* Published URL */}
                    {isPublished && pub.external_url ? (
                      <div className="mt-3 flex items-center justify-between rounded-lg bg-emerald-50 px-3 py-2 text-xs">
                        <span className="font-semibold text-emerald-800">
                          Đã đăng thành công lên YouTube!
                        </span>
                        <a
                          href={pub.external_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="font-extrabold text-emerald-700 hover:underline"
                        >
                          Mở video trên YouTube ↗
                        </a>
                      </div>
                    ) : null}

                    {/* Error message */}
                    {isFailed && pub.error ? (
                      <p className="mt-2 text-xs font-medium text-rose-600">
                        Lỗi: {pub.error}
                      </p>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </Card>
        ) : null}

        {/* Step 6: Recent Manual Publishes History (Requirement 14, 15) */}
        <Card className="p-5 sm:p-6">
          <div className="flex items-center justify-between border-b border-slate-100 pb-3">
            <h2 className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
              Recent Manual Publishes
            </h2>
            <button
              type="button"
              onClick={loadHistory}
              className="text-xs font-semibold text-indigo-600 hover:underline flex items-center gap-1"
            >
              <IconRefresh size={13} />
              Làm mới
            </button>
          </div>

          {loadingHistory ? (
            <div className="py-8 text-center text-xs text-slate-400">
              Đang tải lịch sử…
            </div>
          ) : history.length === 0 ? (
            <div className="py-8 text-center text-xs text-slate-400">
              Chưa có video nào được đăng thủ công.
            </div>
          ) : (
            <div className="mt-4 divide-y divide-slate-100">
              {history.map((item) => {
                const isPublished = item.status === "published";
                const isFailed = item.status === "failed";
                return (
                  <div
                    key={item.id}
                    className="flex flex-col gap-3 py-3.5 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <div className="h-12 w-12 shrink-0 overflow-hidden rounded-lg bg-slate-900">
                        {item.thumbnail ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img
                            src={item.thumbnail}
                            alt=""
                            className="h-full w-full object-cover"
                          />
                        ) : (
                          <div className="flex h-full w-full items-center justify-center text-[10px] text-slate-400">
                            Video
                          </div>
                        )}
                      </div>

                      <div className="min-w-0">
                        <p className="truncate text-sm font-bold text-slate-900">
                          {item.video_title || "Manual Video"}
                        </p>
                        <p className="text-xs text-slate-500 mt-0.5 flex items-center gap-1.5">
                          <span className="font-semibold text-slate-700">
                            {item.destination_name}
                          </span>
                          <span>·</span>
                          <span>{platformLabel(item.platform)}</span>
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-3 shrink-0">
                      {isPublished ? (
                        <Badge tone="green" dot>Published</Badge>
                      ) : isFailed ? (
                        <Badge tone="rose" dot>Failed</Badge>
                      ) : (
                        <Badge tone="blue" dot>{item.status}</Badge>
                      )}

                      {isPublished && item.external_url ? (
                        <a
                          href={item.external_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-bold text-slate-700 hover:bg-slate-50 shadow-sm"
                        >
                          Open YouTube ↗
                        </a>
                      ) : null}

                      {isFailed ? (
                        <button
                          type="button"
                          onClick={() => handleRetry(item.id)}
                          className="inline-flex items-center gap-1 rounded-lg bg-rose-50 border border-rose-200 px-3 py-1.5 text-xs font-bold text-rose-700 hover:bg-rose-100"
                        >
                          Retry
                        </button>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </Card>
      </div>
    </>
  );
}

function SeparateFields({
  destinationId,
  data,
  onChange,
}: {
  destinationId: string;
  data: { title: string; description: string; hashtags: string };
  onChange: (field: "title" | "description" | "hashtags", val: string) => void;
}) {
  return (
    <div className="space-y-4 rounded-xl border border-indigo-100 bg-indigo-50/30 p-4">
      <p className="text-xs font-bold text-indigo-900">
        Tuỳ chỉnh metadata cho Destination ID: <code className="font-mono">{destinationId}</code>
      </p>

      <div>
        <label className="text-xs font-bold text-slate-700">Title</label>
        <input
          type="text"
          value={data.title}
          onChange={(e) => onChange("title", e.target.value)}
          placeholder="Video Title..."
          className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm font-semibold text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none"
        />
      </div>

      <div>
        <label className="text-xs font-bold text-slate-700">Description</label>
        <textarea
          rows={3}
          value={data.description}
          onChange={(e) => onChange("description", e.target.value)}
          placeholder="Video description..."
          className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none"
        />
      </div>

      <div>
        <label className="text-xs font-bold text-slate-700">Hashtags (Exactly 5)</label>
        <input
          type="text"
          value={data.hashtags}
          onChange={(e) => onChange("hashtags", e.target.value)}
          placeholder="#tag1 #tag2 #tag3 #tag4 #tag5"
          className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 font-mono text-sm font-bold text-indigo-600 shadow-sm focus:border-indigo-500 focus:outline-none"
        />
      </div>
    </div>
  );
}
