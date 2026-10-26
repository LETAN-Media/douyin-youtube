"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Badge, Card, CardHeader, Spinner, btnPrimary, btnSecondary, btnSmall, inputCls, labelCls } from "@/components/ui";
import { IconTikTok, IconUpload, IconVideo, IconCheck, IconAlert, IconSparkles } from "@/components/icons";
import type { TikTokDestinationDto, TikTokManualPublicationDto, TikTokManualResolveDto } from "@/lib/tiktok-api";

const STAGE_LABELS: Record<string, string> = {
  queued: "Đang xếp hàng",
  processing: "Đang xử lý",
  resolving_metadata: "Lấy thông tin TikTok",
  resolving_media: "Tải video MP4 (PhimTat)",
  publishing: "Đang upload YouTube",
  completed: "Hoàn tất",
  failed: "Thất bại",
};

function stageLabel(status: string, stage: string | null): string {
  if (status === "done" || status === "published" || stage === "completed") return "Hoàn tất";
  if (status === "failed") return "Thất bại";
  return STAGE_LABELS[stage ?? ""] ?? STAGE_LABELS[status] ?? status;
}

function statusBadge(status: string, stage: string | null) {
  if (status === "done" || status === "published" || stage === "completed") {
    return <Badge tone="green" dot>Hoàn tất</Badge>;
  }
  if (status === "failed") {
    return <Badge tone="red" dot>Thất bại</Badge>;
  }
  return <Badge tone="indigo" dot>{stageLabel(status, stage)}</Badge>;
}

function formatDuration(sec: number | null): string {
  if (sec === null || sec === undefined || Number.isNaN(sec)) return "—";
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function TikTokManualPublish({
  initialPipelines = [],
}: {
  initialPipelines?: { id: string; name: string }[];
}) {
  const [destinations, setDestinations] = useState<TikTokDestinationDto[]>([]);
  const [loadingDests, setLoadingDests] = useState(true);
  const [selectedDestId, setSelectedDestId] = useState<string>("");

  // Create destination dialog
  const [showAddDest, setShowAddDest] = useState(false);
  const [newPipelineId, setNewPipelineId] = useState(initialPipelines[0]?.id || "");
  const [newChannelName, setNewChannelName] = useState("");
  const [creatingDest, setCreatingDest] = useState(false);

  // URL resolution state
  const [url, setUrl] = useState("");
  const [resolving, setResolving] = useState(false);
  const [resolveError, setResolveError] = useState<string | null>(null);
  const [preview, setPreview] = useState<TikTokManualResolveDto | null>(null);

  // Publish form
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [hashtags, setHashtags] = useState("");
  const [visibility, setVisibility] = useState<"public" | "unlisted" | "private">("public");
  const [publishMode, setPublishMode] = useState<"now" | "scheduled">("now");
  const [schedDate, setSchedDate] = useState("");
  const [schedTime, setSchedTime] = useState("");
  const [generatingAi, setGeneratingAi] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);

  // Active publication & polling
  const [activePub, setActivePub] = useState<TikTokManualPublicationDto | null>(null);
  const pollRef = useRef<NodeJS.Timeout | null>(null);

  // History
  const [history, setHistory] = useState<TikTokManualPublicationDto[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);

  const selectedDest = destinations.find((d) => d.id === selectedDestId) || destinations[0] || null;

  // Load destinations on mount
  useEffect(() => {
    let cancelled = false;
    fetch("/api/tiktok/manual/destinations")
      .then((res) => (res.ok ? res.json() : []))
      .then((data: TikTokDestinationDto[]) => {
        if (!cancelled) {
          setDestinations(data);
          if (data.length > 0 && !selectedDestId) {
            setSelectedDestId(data[0].id);
          }
        }
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoadingDests(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedDestId]);

  // Load history whenever destination changes
  const loadHistory = useCallback(async (dest: TikTokDestinationDto | null) => {
    if (!dest) {
      setHistory([]);
      return;
    }
    setLoadingHistory(true);
    try {
      const res = await fetch(
        `/api/tiktok/manual/publications?pipeline_id=${encodeURIComponent(dest.pipeline_id)}&destination_id=${encodeURIComponent(dest.id)}`,
      );
      if (res.ok) {
        const data = await res.json();
        setHistory(Array.isArray(data) ? data : []);
      }
    } catch {
      // ignore
    } finally {
      setLoadingHistory(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    if (!selectedDest) {
      Promise.resolve([]).then((empty) => {
        if (!cancelled) setHistory(empty);
      });
      return () => {
        cancelled = true;
      };
    }
    fetch(
      `/api/tiktok/manual/publications?pipeline_id=${encodeURIComponent(selectedDest.pipeline_id)}&destination_id=${encodeURIComponent(selectedDest.id)}`,
    )
      .then((res) => (res.ok ? res.json() : []))
      .then((data) => {
        if (!cancelled) setHistory(Array.isArray(data) ? data : []);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoadingHistory(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedDest]);

  // Polling for active publication
  useEffect(() => {
    if (!activePub || activePub.status === "done" || activePub.status === "completed" || activePub.status === "failed") {
      if (pollRef.current) clearInterval(pollRef.current);
      return;
    }

    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`/api/tiktok/manual/publications?pub_id=${encodeURIComponent(activePub.id)}`);
        if (res.ok) {
          const updated: TikTokManualPublicationDto = await res.json();
          setActivePub(updated);
          if (updated.status === "done" || updated.status === "completed" || updated.status === "failed") {
            if (pollRef.current) clearInterval(pollRef.current);
            void loadHistory(selectedDest);
          }
        }
      } catch {
        // ignore polling network errors
      }
    }, 2000);

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [activePub, selectedDest, loadHistory]);

  // Resolve video
  async function handleResolve(e?: React.FormEvent) {
    if (e) e.preventDefault();
    const cleanUrl = url.trim();
    if (!cleanUrl || resolving) return;

    setResolving(true);
    setResolveError(null);
    setPreview(null);

    try {
      const res = await fetch("/api/tiktok/manual/resolve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: cleanUrl,
          pipeline_id: selectedDest?.pipeline_id,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || data.message || "Không thể lấy thông tin video TikTok.");
      }
      setPreview(data);
      // Pre-fill form fields (use AI-generated metadata if available, otherwise caption fallback)
      const initialTitle = data.ai_title || (data.caption || "").slice(0, 100);
      const initialDesc = data.ai_description || data.caption || "";
      setTitle(initialTitle);
      setDescription(initialDesc);

      if (Array.isArray(data.ai_hashtags) && data.ai_hashtags.length > 0) {
        setHashtags(data.ai_hashtags.join(" "));
      } else {
        const caption = data.caption || "";
        const tags = caption.match(/#[a-zA-Z0-9_\p{L}]+/gu) || [];
        if (tags.length > 0) {
          setHashtags(tags.slice(0, 10).join(" "));
        }
      }
    } catch (err) {
      setResolveError(err instanceof Error ? err.message : "Lỗi khi nhận diện video.");
    } finally {
      setResolving(false);
    }
  }

  async function handleRegenerateAi() {
    if (!preview || generatingAi) return;
    setGeneratingAi(true);
    try {
      const res = await fetch("/api/tiktok/ai/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pipeline_id: selectedDest?.pipeline_id || "default",
          sample_caption: preview.caption || title,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.title) setTitle(data.title.slice(0, 100));
        if (data.description) setDescription(data.description);
        if (Array.isArray(data.hashtags) && data.hashtags.length > 0) {
          setHashtags(data.hashtags.join(" "));
        }
      }
    } catch {
      // ignore
    } finally {
      setGeneratingAi(false);
    }
  }

  // Create Destination
  async function handleCreateDestination(e: React.FormEvent) {
    e.preventDefault();
    if (!newPipelineId || creatingDest) return;

    setCreatingDest(true);
    try {
      const res = await fetch("/api/tiktok/manual/destinations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pipeline_id: newPipelineId,
          channel_name: newChannelName.trim() || "Kênh YouTube Chính",
          visibility: "public",
        }),
      });
      if (res.ok) {
        const created: TikTokDestinationDto = await res.json();
        setDestinations((prev) => [...prev, created]);
        setSelectedDestId(created.id);
        setShowAddDest(false);
        setNewChannelName("");
      }
    } catch {
      // ignore
    } finally {
      setCreatingDest(false);
    }
  }

  // Publish
  async function handlePublish() {
    if (!selectedDest) {
      setPublishError("Vui lòng chọn hoặc thêm kênh YouTube đích.");
      return;
    }
    if (!url.trim()) {
      setPublishError("Vui lòng nhập link video TikTok.");
      return;
    }
    if (!title.trim()) {
      setPublishError("Tiêu đề không được để trống.");
      return;
    }

    setPublishing(true);
    setPublishError(null);

    let publishAt: string | null = null;
    if (publishMode === "scheduled" && schedDate && schedTime) {
      publishAt = new Date(`${schedDate}T${schedTime}`).toISOString();
    }

    try {
      const res = await fetch("/api/tiktok/manual/publish", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pipeline_id: selectedDest.pipeline_id,
          destination_id: selectedDest.id,
          source_url: url.trim(),
          title: title.trim(),
          description: description.trim(),
          hashtags: hashtags.trim(),
          visibility,
          publish_at: publishAt,
          caption: preview?.caption || title.trim(),
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || data.message || "Không thể gửi yêu cầu đăng.");
      }

      // Track active publication
      const initialPub: TikTokManualPublicationDto = {
        id: data.publication_id,
        destination_id: selectedDest.id,
        pipeline_id: selectedDest.pipeline_id,
        channel_name: selectedDest.channel_name,
        source_url: url.trim(),
        caption: preview?.caption || null,
        thumbnail_url: preview?.thumbnail || null,
        duration: preview?.duration || null,
        youtube_title: title.trim(),
        youtube_description: description.trim(),
        youtube_hashtags_json: JSON.stringify(hashtags.split(" ")),
        visibility,
        publish_at: publishAt,
        status: data.status || "queued",
        stage: "queued",
        youtube_video_id: null,
        error_code: null,
        error: null,
        retry_count: 0,
        created_at: new Date().toISOString(),
        started_at: null,
        completed_at: null,
      };

      setActivePub(initialPub);
      // Reload history
      void loadHistory(selectedDest);
    } catch (err) {
      setPublishError(err instanceof Error ? err.message : "Đăng thất bại.");
    } finally {
      setPublishing(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* Destination & Channel Selector Card */}
      <Card>
        <CardHeader
          title="Kênh YouTube nhận video"
          subtitle="Chọn kênh và pipeline TikTok sẽ nhận video xuất bản"
          icon={<IconTikTok size={18} />}
          action={
            <button
              type="button"
              onClick={() => setShowAddDest(true)}
              className={btnSmall}
            >
              + Thêm kênh đích
            </button>
          }
        />
        <div className="p-4 sm:p-5">
          {loadingDests ? (
            <div className="flex items-center gap-2 text-sm text-slate-500">
              <Spinner /> Đang tải danh sách kênh…
            </div>
          ) : destinations.length === 0 ? (
            <div className="rounded-xl border border-dashed border-slate-200 p-6 text-center">
              <p className="text-sm font-semibold text-slate-700">Chưa có kênh YouTube đích nào</p>
              <p className="mt-1 text-xs text-slate-500">
                Hãy tạo kênh đích để liên kết pipeline TikTok với YouTube
              </p>
              <button
                type="button"
                onClick={() => setShowAddDest(true)}
                className={`mt-4 ${btnPrimary}`}
              >
                + Thêm kênh đích ngay
              </button>
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {destinations.map((d) => {
                const isSelected = selectedDest?.id === d.id;
                return (
                  <button
                    key={d.id}
                    type="button"
                    onClick={() => setSelectedDestId(d.id)}
                    className={`flex flex-col rounded-2xl border p-4 text-left transition ${
                      isSelected
                        ? "border-indigo-500 bg-indigo-50/40 ring-2 ring-indigo-200"
                        : "border-slate-200 bg-white hover:border-slate-300"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-bold text-slate-900 truncate">
                        {d.channel_name || "YouTube Channel"}
                      </span>
                      {d.connected ? (
                        <Badge tone="green" dot>Đã liên kết</Badge>
                      ) : (
                        <Badge tone="amber">Chưa cấp OAuth</Badge>
                      )}
                    </div>
                    <span className="mt-1 text-xs text-slate-500">
                      Pipeline: {d.pipeline_name || d.pipeline_id}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </Card>

      {/* Add Destination Modal */}
      {showAddDest && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
          <div className="w-full max-w-md rounded-3xl border border-slate-200 bg-white p-6 shadow-2xl">
            <h3 className="text-lg font-extrabold text-slate-900">Thêm kênh YouTube đích</h3>
            <form onSubmit={handleCreateDestination} className="mt-4 space-y-4">
              <div>
                <label className={labelCls}>Pipeline TikTok</label>
                <select
                  value={newPipelineId}
                  onChange={(e) => setNewPipelineId(e.target.value)}
                  className={inputCls}
                  required
                >
                  {initialPipelines.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className={labelCls}>Tên kênh YouTube (gợi nhớ)</label>
                <input
                  type="text"
                  value={newChannelName}
                  onChange={(e) => setNewChannelName(e.target.value)}
                  className={inputCls}
                  placeholder="VD: Kênh Shorts Giải Trí"
                  required
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowAddDest(false)}
                  className={btnSecondary}
                  disabled={creatingDest}
                >
                  Hủy
                </button>
                <button type="submit" className={btnPrimary} disabled={creatingDest}>
                  {creatingDest ? "Đang thêm…" : "Tạo kênh đích"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Step 1: Input URL and Resolve */}
      <Card>
        <CardHeader
          title="1. Dán đường dẫn video TikTok"
          subtitle="Hỗ trợ link tiktok.com/@user/video/... và dạng rút gọn vt.tiktok.com/..."
          icon={<IconVideo size={18} />}
        />
        <div className="p-4 sm:p-5">
          <form onSubmit={handleResolve} className="flex flex-col gap-3 sm:flex-row">
            <div className="relative flex-1">
              <input
                type="url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://www.tiktok.com/@creator/video/1234567890..."
                className={`${inputCls} pr-10`}
                disabled={resolving}
                required
              />
            </div>
            <button
              type="submit"
              disabled={resolving || !url.trim()}
              className={`${btnPrimary} min-w-[140px] shrink-0 justify-center`}
            >
              {resolving ? (
                <>
                  <Spinner size={14} /> Đang kiểm tra…
                </>
              ) : (
                "Kiểm tra video"
              )}
            </button>
          </form>

          {resolveError && (
            <div className="mt-3 flex items-start gap-2 rounded-xl bg-rose-50 p-3 text-sm text-rose-700 border border-rose-200">
              <IconAlert size={16} className="mt-0.5 shrink-0" />
              <span>{resolveError}</span>
            </div>
          )}

          {/* Video Preview Card */}
          {preview && (
            <div className="mt-4 flex flex-col gap-4 rounded-2xl border border-indigo-100 bg-indigo-50/30 p-4 sm:flex-row sm:items-center">
              {preview.thumbnail ? (
                <div className="relative h-28 w-20 shrink-0 overflow-hidden rounded-xl bg-slate-900 shadow-sm sm:h-32 sm:w-24">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={preview.thumbnail}
                    alt="Video thumbnail"
                    className="h-full w-full object-cover"
                  />
                  {preview.duration ? (
                    <span className="absolute bottom-1 right-1 rounded bg-black/75 px-1.5 py-0.5 text-[10px] font-bold text-white">
                      {formatDuration(preview.duration)}
                    </span>
                  ) : null}
                </div>
              ) : null}

              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <Badge tone="indigo">Đã nhận diện</Badge>
                  {preview.play_count ? (
                    <span className="text-xs text-slate-500">
                      {Number(preview.play_count).toLocaleString()} lượt xem
                    </span>
                  ) : null}
                </div>
                <p className="mt-1.5 line-clamp-3 text-sm font-semibold text-slate-900">
                  {preview.caption || "Không có caption"}
                </p>
                <p className="mt-1 text-xs text-slate-500 truncate">
                  Video ID: {preview.video_id} • Nguồn: {preview.provider}
                </p>
              </div>
            </div>
          )}
        </div>
      </Card>

      {/* Step 2: Customize YouTube metadata & Publish */}
      {preview && (
        <Card>
          <CardHeader
            title="2. Cấu hình nội dung & Đăng lên YouTube"
            subtitle="Tùy chỉnh tiêu đề, mô tả và chế độ xuất bản"
            icon={<IconUpload size={18} />}
            action={
              <button
                type="button"
                onClick={handleRegenerateAi}
                disabled={generatingAi}
                className="inline-flex items-center gap-1.5 rounded-xl border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-xs font-bold text-indigo-700 shadow-sm transition hover:bg-indigo-100"
              >
                {generatingAi ? <Spinner size={12} /> : <IconSparkles size={13} />}
                <span>{generatingAi ? "AI đang tạo..." : "Tạo lại bằng AI"}</span>
              </button>
            }
          />
          <div className="space-y-4 p-4 sm:p-5">
            <div>
              <div className="flex justify-between items-center mb-1">
                <label className={labelCls}>Tiêu đề YouTube</label>
                <span className={`text-xs ${title.length > 100 ? "text-rose-500 font-bold" : "text-slate-400"}`}>
                  {title.length}/100 ký tự
                </span>
              </div>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                maxLength={100}
                className={inputCls}
                placeholder="Nhập tiêu đề hấp dẫn cho video YouTube"
                required
              />
            </div>

            <div>
              <label className={labelCls}>Mô tả video</label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
                className={inputCls}
                placeholder="Mô tả chi tiết cho video..."
              />
            </div>

            <div>
              <label className={labelCls}>Hashtags</label>
              <input
                type="text"
                value={hashtags}
                onChange={(e) => setHashtags(e.target.value)}
                className={inputCls}
                placeholder="#shorts #tiktok #trending..."
              />
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className={labelCls}>Chế độ hiển thị</label>
                <div className="flex gap-2">
                  {([
                    { val: "public", label: "Công khai" },
                    { val: "unlisted", label: "Không công khai" },
                    { val: "private", label: "Riêng tư" },
                  ] as const).map((opt) => (
                    <button
                      key={opt.val}
                      type="button"
                      onClick={() => setVisibility(opt.val)}
                      className={`flex-1 rounded-xl border py-2 text-xs font-bold transition ${
                        visibility === opt.val
                          ? "border-indigo-600 bg-indigo-50 text-indigo-700"
                          : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                      }`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className={labelCls}>Thời gian xuất bản</label>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => setPublishMode("now")}
                    className={`flex-1 rounded-xl border py-2 text-xs font-bold transition ${
                      publishMode === "now"
                        ? "border-indigo-600 bg-indigo-50 text-indigo-700"
                        : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                    }`}
                  >
                    Đăng ngay
                  </button>
                  <button
                    type="button"
                    onClick={() => setPublishMode("scheduled")}
                    className={`flex-1 rounded-xl border py-2 text-xs font-bold transition ${
                      publishMode === "scheduled"
                        ? "border-indigo-600 bg-indigo-50 text-indigo-700"
                        : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                    }`}
                  >
                    Hẹn giờ
                  </button>
                </div>
              </div>
            </div>

            {publishMode === "scheduled" && (
              <div className="flex gap-3">
                <div className="flex-1">
                  <label className={labelCls}>Ngày đăng</label>
                  <input
                    type="date"
                    value={schedDate}
                    onChange={(e) => setSchedDate(e.target.value)}
                    className={inputCls}
                    required
                  />
                </div>
                <div className="flex-1">
                  <label className={labelCls}>Giờ đăng</label>
                  <input
                    type="time"
                    value={schedTime}
                    onChange={(e) => setSchedTime(e.target.value)}
                    className={inputCls}
                    required
                  />
                </div>
              </div>
            )}

            {publishError && (
              <div className="flex items-center gap-2 rounded-xl bg-rose-50 p-3 text-sm text-rose-700 border border-rose-200">
                <IconAlert size={16} />
                <span>{publishError}</span>
              </div>
            )}

            <div className="pt-2">
              <button
                type="button"
                onClick={handlePublish}
                disabled={publishing}
                className={`${btnPrimary} w-full justify-center py-3 text-base`}
              >
                {publishing ? (
                  <>
                    <Spinner size={16} /> Đang gửi yêu cầu đăng…
                  </>
                ) : (
                  "Đăng lên YouTube"
                )}
              </button>
            </div>
          </div>
        </Card>
      )}

      {/* Active publication progress tracker */}
      {activePub && (
        <Card className="border-indigo-300 bg-indigo-50/20">
          <CardHeader
            title="Tiến trình xuất bản hiện tại"
            subtitle={`Mã tiến trình: ${activePub.id}`}
            icon={<IconUpload size={18} />}
          />
          <div className="p-4 sm:p-5">
            <div className="flex items-center justify-between">
              <div>
                <p className="font-bold text-slate-900">{activePub.youtube_title || "TikTok Video"}</p>
                <p className="text-xs text-slate-500">Kênh đích: {activePub.channel_name || activePub.destination_id}</p>
              </div>
              <div>{statusBadge(activePub.status, activePub.stage)}</div>
            </div>

            {/* Stage progress indicator */}
            <div className="mt-4 grid grid-cols-4 gap-2 text-center text-xs">
              {[
                { key: "queued", label: "1. Xếp hàng" },
                { key: "resolving_metadata", label: "2. TikTok API" },
                { key: "resolving_media", label: "3. Tải MP4" },
                { key: "publishing", label: "4. Upload YouTube" },
              ].map((step, idx) => {
                const isCurrent = activePub.stage === step.key;
                const isDone = activePub.status === "done" || activePub.status === "completed";
                return (
                  <div
                    key={step.key}
                    className={`rounded-xl border p-2 transition ${
                      isDone
                        ? "border-emerald-300 bg-emerald-50 text-emerald-800 font-bold"
                        : isCurrent
                        ? "border-indigo-400 bg-indigo-100 text-indigo-900 font-bold ring-2 ring-indigo-200"
                        : "border-slate-200 bg-white text-slate-500"
                    }`}
                  >
                    {step.label}
                  </div>
                );
              })}
            </div>

            {activePub.youtube_video_id && (
              <div className="mt-4 flex items-center justify-between rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800 border border-emerald-200">
                <span className="flex items-center gap-2">
                  <IconCheck size={16} /> Đã xuất bản thành công!
                </span>
                <a
                  href={`https://www.youtube.com/watch?v=${activePub.youtube_video_id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-bold underline hover:text-emerald-900"
                >
                  Xem video trên YouTube ↗
                </a>
              </div>
            )}

            {activePub.error && (
              <div className="mt-4 rounded-xl bg-rose-50 p-3 text-sm text-rose-800 border border-rose-200">
                <p className="font-bold">Lỗi xuất bản:</p>
                <p className="mt-1 text-xs">{activePub.error}</p>
              </div>
            )}
          </div>
        </Card>
      )}

      {/* History Table */}
      <Card>
        <CardHeader
          title="Lịch sử đăng thủ công gần đây"
          subtitle={selectedDest ? `Kênh: ${selectedDest.channel_name || selectedDest.id}` : "Chọn kênh để xem lịch sử"}
          icon={<IconTikTok size={18} />}
          action={
            <button
              type="button"
              onClick={() => void loadHistory(selectedDest)}
              className={btnSmall}
              disabled={loadingHistory}
            >
              Làm mới
            </button>
          }
        />
        <div className="overflow-x-auto">
          {loadingHistory ? (
            <div className="p-8 text-center text-sm text-slate-500">
              <Spinner /> Đang tải lịch sử…
            </div>
          ) : history.length === 0 ? (
            <div className="p-8 text-center text-sm text-slate-500">
              Chưa có bản đăng thủ công nào cho kênh này.
            </div>
          ) : (
            <table className="w-full text-left text-sm text-slate-700">
              <thead className="border-b border-slate-100 bg-slate-50/75 text-xs uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="px-4 py-3">Video</th>
                  <th className="px-4 py-3">Tiêu đề YouTube</th>
                  <th className="px-4 py-3">Trạng thái</th>
                  <th className="px-4 py-3">Thời gian</th>
                  <th className="px-4 py-3 text-right">Liên kết</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {history.map((row) => (
                  <tr key={row.id} className="hover:bg-slate-50/50">
                    <td className="px-4 py-3">
                      {row.thumbnail_url ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={row.thumbnail_url}
                          alt=""
                          className="h-10 w-8 rounded object-cover shadow-sm"
                        />
                      ) : (
                        <div className="h-10 w-8 rounded bg-slate-100 flex items-center justify-center text-xs text-slate-400">
                          ▶
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <p className="font-semibold text-slate-900 max-w-xs truncate">
                        {row.youtube_title || row.caption || "TikTok Video"}
                      </p>
                      <p className="text-[11px] text-slate-400 truncate max-w-xs">
                        {row.source_url}
                      </p>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      {statusBadge(row.status, row.stage)}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-xs text-slate-500">
                      {row.created_at ? new Date(row.created_at).toLocaleString("vi-VN") : "—"}
                    </td>
                    <td className="px-4 py-3 text-right whitespace-nowrap">
                      {row.youtube_video_id ? (
                        <a
                          href={`https://www.youtube.com/watch?v=${row.youtube_video_id}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-xs font-bold text-indigo-600 hover:text-indigo-800"
                        >
                          YouTube ↗
                        </a>
                      ) : row.status === "failed" ? (
                        <span className="text-xs text-rose-500 truncate max-w-[120px] inline-block" title={row.error || ""}>
                          {row.error || "Lỗi"}
                        </span>
                      ) : (
                        <span className="text-xs text-slate-400">Đang xử lý</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </Card>
    </div>
  );
}
