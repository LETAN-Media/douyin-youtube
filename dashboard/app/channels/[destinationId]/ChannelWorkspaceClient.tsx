"use client";

import { useState, useTransition, useCallback, useRef, useEffect } from "react";
import Link from "next/link";
import { Badge, Card, ProgressBar } from "@/components/ui";
import {
  IconAlert,
  IconBack,
  IconCheck,
  IconClock,
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
  ChannelDetail,
  ManualMetadataResult,
  ManualPublicationItem,
  ManualPublishPayload,
  ManualPublishResponse,
  ManualResolveResult,
} from "@/lib/types";
import { actionGetOauthUrl, actionToggleDestination, actionUpdateDestination } from "@/lib/actions";

function formatDuration(sec?: number | null): string {
  if (sec == null || sec <= 0) return "00:00";
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

interface ChannelWorkspaceClientProps {
  initialDetail: ChannelDetail;
}

export function ChannelWorkspaceClient({ initialDetail }: ChannelWorkspaceClientProps) {
  const [detail, setDetail] = useState<ChannelDetail>(initialDetail);
  const [activeTab, setActiveTab] = useState<"manual" | "auto" | "queue" | "published" | "settings">("manual");
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
  // TAB 1: MANUAL PUBLISH STATE
  // ==========================================
  const [input, setInput] = useState("");
  const [resolving, setResolving] = useState(false);
  const [resolveError, setResolveError] = useState<string | null>(null);
  const [resolvedVideo, setResolvedVideo] = useState<ManualResolveResult | null>(null);
  const [profileDetected, setProfileDetected] = useState<ManualResolveResult | null>(null);

  const [privacy, setPrivacy] = useState<"public" | "unlisted" | "private">("public");
  const [generateAi, setGenerateAi] = useState(true);

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [hashtags, setHashtags] = useState("");
  const [generatingMetadata, setGeneratingMetadata] = useState(false);
  const [metadataError, setMetadataError] = useState<string | null>(null);

  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);
  const [duplicateWarning, setDuplicateWarning] = useState<{
    message: string;
    external_url?: string;
  } | null>(null);

  const [activePublications, setActivePublications] = useState<ManualPublicationItem[]>([]);

  // Generate metadata helper
  const triggerAiMetadata = useCallback(
    async (sourceUrl: string, captionText: string) => {
      setGeneratingMetadata(true);
      setMetadataError(null);
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
      setHashtags("#shorts #trending #viral #video #fyp");

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
        privacy_status: privacy,
        force_duplicate: forceDuplicate,
      };

      const res = await fetch("/api/manual/publish", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await res.json();

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

      const result: ManualPublishResponse = data;
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

  // ==========================================
  // TAB 5: SETTINGS FORM STATE
  // ==========================================
  const [settingsName, setSettingsName] = useState(channel.channel_title || "");
  const [settingsLimit, setSettingsLimit] = useState(detail.daily_upload_limit || 6);
  const [settingsProfile, setSettingsProfile] = useState(detail.metadata_profile || "");
  const [settingsLanguage, setSettingsLanguage] = useState(detail.metadata_language || "");
  const [settingsHashtags, setSettingsHashtags] = useState(detail.fixed_hashtags || "");
  const [savingSettings, setSavingSettings] = useState(false);
  const [settingsSuccess, setSettingsSuccess] = useState(false);

  const handleSaveSettings = async (e: React.FormEvent) => {
    e.preventDefault();
    setSavingSettings(true);
    setSettingsSuccess(false);

    try {
      const form = new FormData();
      form.set("name", settingsName);
      form.set("daily_upload_limit", String(settingsLimit));
      form.set("metadata_profile", settingsProfile);
      form.set("metadata_language", settingsLanguage);
      form.set("fixed_hashtags", settingsHashtags);

      const res = await actionUpdateDestination(channel.pipeline_id, channel.destination_id, form);
      if (res.ok) {
        setSettingsSuccess(true);
        setTimeout(() => setSettingsSuccess(false), 4000);
        reloadDetail();
      } else {
        alert(res.error || "Lưu cài đặt thất bại");
      }
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Lỗi lưu cài đặt");
    } finally {
      setSavingSettings(false);
    }
  };

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

      {/* CHANNEL HEADER */}
      <Card className="overflow-hidden p-0">
        <div className="h-1.5 bg-gradient-to-r from-red-600 via-rose-500 to-indigo-600" />
        <div className="p-5 sm:p-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            {/* Avatar & Title */}
            <div className="flex items-start gap-4">
              <div className="relative h-14 w-14 shrink-0 overflow-hidden rounded-2xl bg-slate-900 ring-1 ring-slate-900/10 shadow-sm">
                {channel.avatar_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={channel.avatar_url}
                    alt={channel.channel_title}
                    className="h-full w-full object-cover"
                  />
                ) : (
                  <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-rose-500 to-red-600 text-xl font-black text-white">
                    {(channel.channel_title || "Y")[0].toUpperCase()}
                  </div>
                )}
                <span className="absolute bottom-0 right-0 flex h-4 w-4 items-center justify-center rounded-tl-md bg-red-600 text-[8px] font-black text-white">
                  YT
                </span>
              </div>

              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="truncate text-xl font-black text-slate-900">
                    {channel.channel_title}
                  </h1>
                  <span className="inline-flex items-center rounded-md bg-red-50 px-2 py-0.5 font-extrabold text-red-700 text-xs">
                    YouTube
                  </span>
                  {isConnected ? (
                    <Badge tone="green" dot>Connected</Badge>
                  ) : (
                    <Badge tone="slate" dot>Not Connected</Badge>
                  )}
                  {channel.enabled ? (
                    <Badge tone="green">Active</Badge>
                  ) : (
                    <Badge tone="amber">Paused</Badge>
                  )}
                </div>

                <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-slate-500">
                  <span>
                    Pipeline:{" "}
                    <Link
                      href={`/pipelines/${channel.pipeline_id}`}
                      className="font-bold text-slate-700 hover:text-indigo-600 hover:underline"
                    >
                      {channel.pipeline_name}
                    </Link>
                  </span>
                  {channel.channel_id ? (
                    <span>
                      ID: <code className="font-mono text-slate-600">{channel.channel_id}</code>
                    </span>
                  ) : null}
                </div>
              </div>
            </div>

            {/* Quick Actions */}
            <div className="flex flex-wrap items-center gap-2">
              {channel.channel_id ? (
                <a
                  href={`https://www.youtube.com/channel/${channel.channel_id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex min-h-[44px] items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-bold text-slate-700 shadow-sm hover:bg-slate-50 transition"
                >
                  Open on YouTube ↗
                </a>
              ) : null}

              <button
                type="button"
                onClick={handleReconnect}
                disabled={pending}
                className="inline-flex min-h-[44px] items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-bold text-slate-700 shadow-sm hover:bg-slate-50 transition disabled:opacity-50"
              >
                {pending ? "…" : isConnected ? "Reconnect" : "Connect OAuth"}
              </button>

              <button
                type="button"
                onClick={handleToggleEnabled}
                disabled={pending}
                className={`inline-flex min-h-[44px] items-center rounded-xl px-3.5 py-2 text-xs font-bold transition ${
                  channel.enabled
                    ? "bg-slate-100 text-slate-700 hover:bg-slate-200"
                    : "bg-emerald-600 text-white hover:bg-emerald-500"
                }`}
              >
                {channel.enabled ? "Pause Channel" : "Resume Channel"}
              </button>
            </div>
          </div>

          {/* Stats Bar */}
          <div className="mt-5 grid grid-cols-2 gap-3 border-t border-slate-100 pt-4 sm:grid-cols-4">
            <div className="rounded-xl bg-slate-50 p-3 text-xs">
              <span className="font-medium text-slate-400">Published today</span>
              <p className="mt-1 text-lg font-black text-slate-900">{channel.published_today}</p>
            </div>
            <div className="rounded-xl bg-slate-50 p-3 text-xs">
              <span className="font-medium text-slate-400">Queue pending</span>
              <p className="mt-1 text-lg font-black text-slate-900">{channel.queue_count}</p>
            </div>
            <div className="rounded-xl bg-slate-50 p-3 text-xs">
              <span className="font-medium text-slate-400">Daily limit</span>
              <p className="mt-1 text-lg font-black text-slate-900">{detail.daily_upload_limit} / day</p>
            </div>
            <div className="rounded-xl bg-slate-50 p-3 text-xs">
              <span className="font-medium text-slate-400">Timezone</span>
              <p className="mt-1 text-base font-bold text-slate-900 truncate">{detail.timezone}</p>
            </div>
          </div>
        </div>
      </Card>

      {/* TABS NAVIGATION */}
      <div className="flex items-center gap-2 border-b border-slate-200 overflow-x-auto pb-1">
        <button
          type="button"
          onClick={() => setActiveTab("manual")}
          className={`flex min-h-[44px] items-center gap-2 border-b-2 px-4 py-2.5 text-xs font-extrabold transition whitespace-nowrap ${
            activeTab === "manual"
              ? "border-indigo-600 text-indigo-700"
              : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800"
          }`}
        >
          <IconUpload size={16} />
          Manual
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("auto")}
          className={`flex min-h-[44px] items-center gap-2 border-b-2 px-4 py-2.5 text-xs font-extrabold transition whitespace-nowrap ${
            activeTab === "auto"
              ? "border-indigo-600 text-indigo-700"
              : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800"
          }`}
        >
          <IconSources size={16} />
          Auto
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("queue")}
          className={`flex min-h-[44px] items-center gap-2 border-b-2 px-4 py-2.5 text-xs font-extrabold transition whitespace-nowrap ${
            activeTab === "queue"
              ? "border-indigo-600 text-indigo-700"
              : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800"
          }`}
        >
          <IconClock size={16} />
          Queue
          {detail.queue.length > 0 ? (
            <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-[10px] font-black text-indigo-700">
              {detail.queue.length}
            </span>
          ) : null}
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("published")}
          className={`flex min-h-[44px] items-center gap-2 border-b-2 px-4 py-2.5 text-xs font-extrabold transition whitespace-nowrap ${
            activeTab === "published"
              ? "border-indigo-600 text-indigo-700"
              : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800"
          }`}
        >
          <IconPublications size={16} />
          Published
          {detail.published.length > 0 ? (
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-black text-slate-700">
              {detail.published.length}
            </span>
          ) : null}
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("settings")}
          className={`flex min-h-[44px] items-center gap-2 border-b-2 px-4 py-2.5 text-xs font-extrabold transition whitespace-nowrap ${
            activeTab === "settings"
              ? "border-indigo-600 text-indigo-700"
              : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800"
          }`}
        >
          <IconSettings size={16} />
          Settings
        </button>
      </div>

      {/* ============================================================ */}
      {/* TAB 1: MANUAL (DEFAULT) */}
      {/* ============================================================ */}
      {activeTab === "manual" && (
        <div className="space-y-6">
          <Card className="p-5 sm:p-6">
            <div className="flex flex-col gap-2">
              <label htmlFor="douyin-channel-input" className="text-sm font-extrabold text-slate-900">
                Dán link Douyin để đăng ngay lên kênh {channel.channel_title}
              </label>
              <p className="text-xs text-slate-500">
                Destination được cấu hình sẵn cho kênh này. Nhấn <kbd className="rounded border border-slate-200 bg-slate-100 px-1.5 py-0.5 font-mono text-xs font-semibold text-slate-700">Enter</kbd> để phân tích và chuẩn bị đăng video.
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

          {/* Profile link warning */}
          {profileDetected ? (
            <Card className="border-amber-300 bg-amber-50/70 p-5">
              <div className="flex items-start gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-amber-100 text-amber-700">
                  <IconAlert size={20} />
                </span>
                <div>
                  <p className="text-sm font-extrabold text-amber-900">
                    This is a Douyin profile, not a single video.
                  </p>
                  <p className="mt-0.5 text-xs text-amber-700">
                    Manual Publish chỉ đăng từng video đơn lẻ. Vui lòng dán link video cụ thể.
                  </p>
                </div>
              </div>
            </Card>
          ) : null}

          {/* Video Preview & Metadata Form */}
          {resolvedVideo ? (
            <div className="space-y-6">
              <Card className="p-5 sm:p-6">
                <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                  <h2 className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
                    Video Preview
                  </h2>
                  <Badge tone="green" dot>{resolvedVideo.status}</Badge>
                </div>

                <div className="mt-4 flex flex-col gap-4 sm:flex-row sm:items-start sm:gap-6">
                  <div className="relative aspect-[9/16] w-full max-w-[140px] shrink-0 overflow-hidden rounded-xl bg-slate-900 shadow-sm sm:w-36">
                    {resolvedVideo.thumbnail ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={resolvedVideo.thumbnail}
                        alt="Preview"
                        className="h-full w-full object-cover"
                      />
                    ) : (
                      <div className="flex h-full w-full items-center justify-center text-xs text-slate-500">
                        No preview
                      </div>
                    )}
                    {resolvedVideo.duration ? (
                      <span className="absolute bottom-2 right-2 rounded-md bg-black/80 px-1.5 py-0.5 font-mono text-[10px] font-extrabold text-white">
                        {formatDuration(resolvedVideo.duration)}
                      </span>
                    ) : null}
                  </div>

                  <div className="flex-1 space-y-2 text-xs">
                    <p className="text-sm font-bold text-slate-900">
                      Tác giả: {resolvedVideo.author || "Douyin Creator"}
                    </p>
                    <p className="text-slate-700 leading-relaxed">
                      {resolvedVideo.caption || "Không có caption"}
                    </p>
                    <a
                      href={resolvedVideo.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-block font-semibold text-indigo-600 hover:underline pt-1"
                    >
                      Mở link Douyin gốc ↗
                    </a>
                  </div>
                </div>
              </Card>

              {/* Metadata Form */}
              <Card className="p-5 sm:p-6">
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 pb-3">
                  <h2 className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
                    Metadata & Content (Đăng lên {channel.channel_title})
                  </h2>

                  <div className="flex items-center gap-3">
                    {/* Privacy Selector */}
                    <div className="flex items-center gap-1 rounded-xl border border-slate-200 bg-slate-50 p-1">
                      <span className="px-2 text-xs font-semibold text-slate-500">Privacy:</span>
                      {(["public", "unlisted", "private"] as const).map((p) => (
                        <button
                          key={p}
                          type="button"
                          onClick={() => setPrivacy(p)}
                          className={`rounded-lg px-2.5 py-1 text-xs font-bold capitalize transition ${
                            privacy === p
                              ? "bg-white text-indigo-700 shadow-sm"
                              : "text-slate-600 hover:text-slate-900"
                          }`}
                        >
                          {p}
                        </button>
                      ))}
                    </div>

                    <label className="flex items-center gap-1.5 text-xs font-bold text-indigo-700 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={generateAi}
                        onChange={(e) => setGenerateAi(e.target.checked)}
                        className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                      />
                      <IconSparkles size={14} />
                      AI Metadata
                    </label>
                  </div>
                </div>

                <div className="mt-4 space-y-4">
                  {metadataError ? (
                    <p className="rounded-xl border border-rose-200 bg-rose-50 p-2.5 text-xs font-semibold text-rose-700">
                      {metadataError}
                    </p>
                  ) : null}

                  {generatingMetadata ? (
                    <div className="flex items-center gap-2 text-xs font-bold text-indigo-600 py-2">
                      <span className="h-4 w-4 animate-spin rounded-full border-2 border-indigo-600 border-t-transparent" />
                      Đang sinh AI metadata theo profile kênh…
                    </div>
                  ) : null}

                  <div>
                    <label className="text-xs font-bold text-slate-700">Tiêu đề YouTube (Title)</label>
                    <input
                      type="text"
                      value={title}
                      onChange={(e) => setTitle(e.target.value)}
                      placeholder="YouTube Title..."
                      className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm font-semibold text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none"
                    />
                  </div>

                  <div>
                    <label className="text-xs font-bold text-slate-700">Mô tả (Description)</label>
                    <textarea
                      rows={3}
                      value={description}
                      onChange={(e) => setDescription(e.target.value)}
                      placeholder="Mô tả nội dung video..."
                      className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none"
                    />
                  </div>

                  <div>
                    <label className="text-xs font-bold text-slate-700">Hashtags (5 tags)</label>
                    <input
                      type="text"
                      value={hashtags}
                      onChange={(e) => setHashtags(e.target.value)}
                      placeholder="#tag1 #tag2 #tag3 #tag4 #tag5"
                      className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 font-mono text-sm font-bold text-indigo-600 shadow-sm focus:border-indigo-500 focus:outline-none"
                    />
                  </div>

                  {/* Actions */}
                  <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4">
                    <button
                      type="button"
                      onClick={() => triggerAiMetadata(resolvedVideo.source_url, resolvedVideo.caption || "")}
                      disabled={generatingMetadata}
                      className="inline-flex min-h-[40px] items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs font-bold text-slate-700 shadow-sm hover:bg-slate-50"
                    >
                      <IconRefresh size={14} />
                      Regenerate AI
                    </button>

                    <button
                      type="button"
                      onClick={() => handlePublish(false)}
                      disabled={publishing}
                      className="inline-flex min-h-[46px] items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-indigo-600 to-indigo-700 px-7 py-2.5 text-sm font-extrabold text-white shadow-lg hover:from-indigo-500 hover:to-indigo-600 disabled:opacity-50"
                    >
                      {publishing ? (
                        <>
                          <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                          Đang tạo job…
                        </>
                      ) : (
                        <>
                          <IconUpload size={17} />
                          Publish Now to {channel.channel_title}
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

              {/* Duplicate Warning */}
              {duplicateWarning ? (
                <div className="rounded-2xl border border-amber-300 bg-amber-50 p-5 shadow-md">
                  <div className="flex items-start gap-3">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-amber-200 text-amber-800">
                      <IconAlert size={18} />
                    </span>
                    <div className="flex-1">
                      <p className="text-sm font-extrabold text-amber-900">{duplicateWarning.message}</p>
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
                          Cancel
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
            </div>
          ) : null}

          {/* Live Progress for publications triggered from this tab */}
          {activePublications.length > 0 ? (
            <Card className="p-5 border-indigo-200 bg-indigo-50/20">
              <h3 className="text-xs font-extrabold uppercase tracking-wider text-indigo-900 mb-3">
                Tiến độ xuất bản gần nhất
              </h3>
              <div className="space-y-3">
                {activePublications.map((pub) => {
                  const isPub = pub.status === "published";
                  const isFail = pub.status === "failed";
                  return (
                    <div key={pub.id} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-sm font-bold text-slate-900 truncate">
                          {pub.video_title || "Video Publication"}
                        </p>
                        {isPub ? (
                          <Badge tone="green" dot>Published</Badge>
                        ) : isFail ? (
                          <Badge tone="rose" dot>Failed</Badge>
                        ) : (
                          <Badge tone="blue" dot>{pub.status}</Badge>
                        )}
                      </div>

                      {!isPub && !isFail ? (
                        <div className="mt-2.5">
                          <ProgressBar value={pub.progress || 30} tone="indigo" />
                        </div>
                      ) : null}

                      {isPub && pub.external_url ? (
                        <div className="mt-2 text-xs">
                          <a
                            href={pub.external_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="font-bold text-emerald-700 hover:underline"
                          >
                            Mở video trên YouTube ↗
                          </a>
                        </div>
                      ) : null}

                      {isFail ? (
                        <button
                          type="button"
                          onClick={() => handleRetryPub(pub.id)}
                          className="mt-2 rounded-lg bg-rose-50 border border-rose-200 px-3 py-1 text-xs font-bold text-rose-700"
                        >
                          Thử lại
                        </button>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            </Card>
          ) : null}
        </div>
      )}

      {/* ============================================================ */}
      {/* TAB 2: AUTO */}
      {/* ============================================================ */}
      {activeTab === "auto" && (
        <div className="space-y-6">
          <Card className="p-5 sm:p-6">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div>
                <h3 className="text-sm font-extrabold text-slate-900">
                  Cấu hình Auto Publishing cho {channel.channel_title}
                </h3>
                <p className="text-xs text-slate-500 mt-0.5">
                  Kênh này được liên kết với Pipeline <strong>{detail.pipeline.name}</strong>. Video từ Douyin Sources sẽ được tự động quét vào Inventory và xuất bản theo lịch.
                </p>
              </div>
              <Link
                href={`/pipelines/${detail.pipeline.id}`}
                className="inline-flex min-h-[40px] items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-1.5 text-xs font-bold text-indigo-600 shadow-sm hover:bg-slate-50"
              >
                Quản lý Pipeline →
              </Link>
            </div>

            <div className="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
              <div className="rounded-xl border border-slate-100 bg-slate-50 p-3">
                <span className="text-slate-400 font-medium">Pipeline Status</span>
                <p className="mt-1 font-bold text-slate-900">
                  {detail.pipeline.enabled ? "Active" : "Paused"}
                </p>
              </div>
              <div className="rounded-xl border border-slate-100 bg-slate-50 p-3">
                <span className="text-slate-400 font-medium">Default Privacy</span>
                <p className="mt-1 font-bold text-slate-900 capitalize">{detail.pipeline.default_privacy}</p>
              </div>
              <div className="rounded-xl border border-slate-100 bg-slate-50 p-3">
                <span className="text-slate-400 font-medium">Upload Slots</span>
                <p className="mt-1 font-bold text-slate-900 truncate">
                  {detail.pipeline.upload_slots.length > 0
                    ? detail.pipeline.upload_slots.join(", ")
                    : "Mặc định (6 slots)"}
                </p>
              </div>
            </div>

            {/* Sources list */}
            <div className="mt-6">
              <h4 className="text-xs font-extrabold uppercase tracking-wider text-slate-500 mb-3">
                Douyin Sources ({detail.sources.length})
              </h4>
              {detail.sources.length === 0 ? (
                <p className="text-xs text-slate-400 py-3">Chưa có Douyin source nào được liên kết.</p>
              ) : (
                <div className="divide-y divide-slate-100 rounded-xl border border-slate-100 overflow-hidden">
                  {detail.sources.map((src) => (
                    <div key={src.id} className="flex items-center justify-between p-3 bg-white text-xs">
                      <div>
                        <p className="font-bold text-slate-900">{src.name}</p>
                        {src.profile_url ? (
                          <a
                            href={src.profile_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-[11px] text-indigo-600 hover:underline"
                          >
                            {src.profile_url}
                          </a>
                        ) : null}
                      </div>
                      <div className="flex items-center gap-3">
                        <span className="text-slate-500">{src.video_count} videos</span>
                        <Badge tone={src.status === "idle" ? "slate" : "indigo"}>{src.status}</Badge>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </Card>
        </div>
      )}

      {/* ============================================================ */}
      {/* TAB 3: QUEUE */}
      {/* ============================================================ */}
      {activeTab === "queue" && (
        <Card className="p-5 sm:p-6">
          <div className="flex items-center justify-between border-b border-slate-100 pb-3">
            <h3 className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
              Queue ({detail.queue.length})
            </h3>
            <button
              type="button"
              onClick={reloadDetail}
              className="text-xs font-semibold text-indigo-600 hover:underline flex items-center gap-1"
            >
              <IconRefresh size={13} />
              Làm mới
            </button>
          </div>

          {detail.queue.length === 0 ? (
            <div className="py-12 text-center text-xs text-slate-400">
              Hàng chờ trống. Không có video nào đang chờ xuất bản trên kênh này.
            </div>
          ) : (
            <div className="mt-4 space-y-3">
              {detail.queue.map((item) => (
                <div
                  key={item.id}
                  className="flex flex-col gap-3 rounded-xl border border-slate-100 bg-white p-4 shadow-sm sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="h-12 w-12 shrink-0 overflow-hidden rounded-lg bg-slate-900">
                      {item.thumbnail ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={item.thumbnail} alt="" className="h-full w-full object-cover" />
                      ) : (
                        <div className="flex h-full w-full items-center justify-center text-[10px] text-slate-400">
                          Video
                        </div>
                      )}
                    </div>
                    <div className="min-w-0">
                      <p className="font-bold text-slate-900 truncate text-sm">
                        {item.video_title || "Untitled Video"}
                      </p>
                      <p className="text-xs text-slate-400 mt-0.5">
                        Tạo lúc: {new Date(item.created_at).toLocaleString()}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-3 shrink-0">
                    <Badge tone={item.status === "failed" ? "rose" : "blue"} dot>
                      {item.status}
                    </Badge>
                    {item.status === "failed" ? (
                      <button
                        type="button"
                        onClick={() => handleRetryPub(item.id)}
                        className="rounded-lg bg-rose-50 border border-rose-200 px-3 py-1 text-xs font-bold text-rose-700 hover:bg-rose-100"
                      >
                        Thử lại
                      </button>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      {/* ============================================================ */}
      {/* TAB 4: PUBLISHED */}
      {/* ============================================================ */}
      {activeTab === "published" && (
        <Card className="p-5 sm:p-6">
          <div className="flex items-center justify-between border-b border-slate-100 pb-3">
            <h3 className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
              Published ({detail.published.length})
            </h3>
            <button
              type="button"
              onClick={reloadDetail}
              className="text-xs font-semibold text-indigo-600 hover:underline flex items-center gap-1"
            >
              <IconRefresh size={13} />
              Làm mới
            </button>
          </div>

          {detail.published.length === 0 ? (
            <div className="py-12 text-center text-xs text-slate-400">
              Chưa có video nào được xuất bản thành công trên kênh này.
            </div>
          ) : (
            <div className="mt-4 divide-y divide-slate-100">
              {detail.published.map((item) => (
                <div
                  key={item.id}
                  className="flex flex-col gap-3 py-3.5 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="h-12 w-12 shrink-0 overflow-hidden rounded-lg bg-slate-900">
                      {item.thumbnail ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={item.thumbnail} alt="" className="h-full w-full object-cover" />
                      ) : (
                        <div className="flex h-full w-full items-center justify-center text-[10px] text-slate-400">
                          Video
                        </div>
                      )}
                    </div>
                    <div className="min-w-0">
                      <p className="font-bold text-slate-900 truncate text-sm">
                        {item.video_title || "Published Video"}
                      </p>
                      <p className="text-xs text-slate-400 mt-0.5">
                        {item.published_at
                          ? `Đã đăng: ${new Date(item.published_at).toLocaleString()}`
                          : "Đã xuất bản"}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-3 shrink-0">
                    <Badge tone="green" dot>Published</Badge>
                    {item.external_url ? (
                      <a
                        href={item.external_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex min-h-[40px] items-center gap-1 rounded-xl border border-slate-200 bg-white px-3.5 py-1.5 text-xs font-bold text-slate-700 shadow-sm hover:bg-slate-50"
                      >
                        Open YouTube ↗
                      </a>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      {/* ============================================================ */}
      {/* TAB 5: SETTINGS */}
      {/* ============================================================ */}
      {activeTab === "settings" && (
        <Card className="p-5 sm:p-6">
          <h3 className="text-sm font-extrabold text-slate-900 border-b border-slate-100 pb-3">
            Cài đặt Channel {channel.channel_title}
          </h3>

          <form onSubmit={handleSaveSettings} className="mt-5 space-y-4 max-w-xl">
            {settingsSuccess ? (
              <p className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs font-bold text-emerald-800">
                ✓ Đã cập nhật thông tin channel thành công!
              </p>
            ) : null}

            <div>
              <label className="text-xs font-bold text-slate-700">Tên Channel hiển thị</label>
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
              <label className="text-xs font-bold text-slate-700">Daily Upload Limit (videos/ngày)</label>
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
              <label className="text-xs font-bold text-slate-700">AI Metadata Profile</label>
              <input
                type="text"
                value={settingsProfile}
                onChange={(e) => setSettingsProfile(e.target.value)}
                placeholder="Ví dụ: fitness, tech, entertainment, male_aesthetic..."
                className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none"
              />
            </div>

            <div>
              <label className="text-xs font-bold text-slate-700">Ngôn ngữ tiêu đề / mô tả (Language)</label>
              <input
                type="text"
                value={settingsLanguage}
                onChange={(e) => setSettingsLanguage(e.target.value)}
                placeholder="Ví dụ: vi, en, zh..."
                className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none"
              />
            </div>

            <div>
              <label className="text-xs font-bold text-slate-700">Fixed Hashtags (cách nhau bởi dấu cách)</label>
              <input
                type="text"
                value={settingsHashtags}
                onChange={(e) => setSettingsHashtags(e.target.value)}
                placeholder="#shorts #viral #vibemen"
                className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 font-mono text-sm font-bold text-indigo-600 shadow-sm focus:border-indigo-500 focus:outline-none"
              />
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
