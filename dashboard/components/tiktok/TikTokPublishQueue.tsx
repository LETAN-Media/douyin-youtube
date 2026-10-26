"use client";

import { useEffect, useState, useCallback } from "react";
import Image from "next/image";
import { Badge, Card, CardHeader, Spinner, btnPrimary, btnSecondary, btnSmall } from "@/components/ui";
import {
  IconAlert,
  IconCheck,
  IconClock,
  IconFilm,
  IconPlay,
  IconRefresh,
  IconTikTok,
  IconUpload,
  IconVideo,
} from "@/components/icons";
import type { TikTokQueueJobDto } from "@/lib/tiktok-api";

interface Props {
  pipelineId: string;
}

function formatDateTime(isoString: string | null | undefined): string {
  if (!isoString) return "—";
  try {
    const d = new Date(isoString);
    if (Number.isNaN(d.getTime())) return isoString;
    return d.toLocaleString("vi-VN", {
      timeZone: "Asia/Ho_Chi_Minh",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return isoString;
  }
}

export function TikTokPublishQueue({ pipelineId }: Props) {
  const [jobs, setJobs] = useState<TikTokQueueJobDto[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [actionJobId, setActionJobId] = useState<string | null>(null);

  // Reschedule modal state
  const [rescheduleJob, setRescheduleJob] = useState<TikTokQueueJobDto | null>(null);
  const [newScheduleTime, setNewScheduleTime] = useState("");
  const [rescheduling, setRescheduling] = useState(false);

  // Detail modal state
  const [detailJob, setDetailJob] = useState<TikTokQueueJobDto | null>(null);

  const fetchQueue = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/tiktok/pipelines/${encodeURIComponent(pipelineId)}/queue`);
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data = await res.json();
      setJobs(Array.isArray(data) ? data : []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Không tải được hàng đợi.");
    } finally {
      setLoading(false);
    }
  }, [pipelineId]);

  useEffect(() => {
    fetchQueue();
  }, [fetchQueue]);

  async function handleRetry(jobId: string) {
    setActionJobId(jobId);
    setActionMessage(null);
    try {
      const res = await fetch(`/api/tiktok/queue/${encodeURIComponent(jobId)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "retry" }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.message || data.error || "Không thể thử lại job.");
      }
      setActionMessage({ type: "success", text: "Đã đưa job trở lại hàng đợi xử lý." });
      await fetchQueue();
    } catch (err: unknown) {
      setActionMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Lỗi khi thử lại job.",
      });
    } finally {
      setActionJobId(null);
    }
  }

  async function handleCancel(jobId: string) {
    if (!confirm("Bạn có chắc chắn muốn hủy lượt đăng video này?")) return;
    setActionJobId(jobId);
    setActionMessage(null);
    try {
      const res = await fetch(`/api/tiktok/queue/${encodeURIComponent(jobId)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "cancel" }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.message || data.error || "Không thể hủy job.");
      }
      setActionMessage({ type: "success", text: "Đã hủy job và giải phóng video về kho." });
      await fetchQueue();
    } catch (err: unknown) {
      setActionMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Lỗi khi hủy job.",
      });
    } finally {
      setActionJobId(null);
    }
  }

  async function handleRescheduleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!rescheduleJob || !newScheduleTime || rescheduling) return;
    setRescheduling(true);
    try {
      const utcIso = new Date(newScheduleTime).toISOString();
      const res = await fetch(`/api/tiktok/queue/${encodeURIComponent(rescheduleJob.id)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "reschedule", scheduled_at: utcIso }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.message || data.error || "Không thể đổi lịch đăng.");
      }
      setActionMessage({ type: "success", text: "Đã cập nhật lịch đăng thành công." });
      setRescheduleJob(null);
      await fetchQueue();
    } catch (err: unknown) {
      setActionMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Lỗi khi đổi lịch đăng.",
      });
    } finally {
      setRescheduling(false);
    }
  }

  const queuedCount = jobs.filter((j) => j.status === "queued").length;
  const processingCount = jobs.filter((j) => j.status === "processing").length;
  const doneCount = jobs.filter((j) => j.status === "done" || j.status === "published").length;
  const failedCount = jobs.filter((j) => j.status === "failed").length;

  return (
    <div className="space-y-6">
      {/* Top summary & actions */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-extrabold text-slate-900 sm:text-xl">Hàng đợi xuất bản (Publish Queue)</h2>
          <p className="mt-0.5 text-xs text-slate-500">
            Theo dõi danh sách video đã lên lịch, đang xử lý và đã đăng lên YouTube theo Pipeline hiện tại.
          </p>
        </div>
        <button
          type="button"
          onClick={fetchQueue}
          disabled={loading}
          className={`${btnSecondary} inline-flex items-center gap-1.5 self-start sm:self-auto min-h-[38px] px-3.5 text-xs font-semibold`}
        >
          <IconRefresh size={14} className={loading ? "animate-spin" : ""} />
          Làm mới
        </button>
      </div>

      {/* Metric Cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-xl border border-slate-200/90 bg-white p-3.5 shadow-sm">
          <p className="text-xs font-medium text-slate-500">Chờ đăng (Queued)</p>
          <p className="mt-1 text-2xl font-black text-amber-600">{queuedCount}</p>
        </div>
        <div className="rounded-xl border border-slate-200/90 bg-white p-3.5 shadow-sm">
          <p className="text-xs font-medium text-slate-500">Đang xử lý (Processing)</p>
          <p className="mt-1 text-2xl font-black text-indigo-600">{processingCount}</p>
        </div>
        <div className="rounded-xl border border-slate-200/90 bg-white p-3.5 shadow-sm">
          <p className="text-xs font-medium text-slate-500">Đã đăng thành công</p>
          <p className="mt-1 text-2xl font-black text-emerald-600">{doneCount}</p>
        </div>
        <div className="rounded-xl border border-slate-200/90 bg-white p-3.5 shadow-sm">
          <p className="text-xs font-medium text-slate-500">Thất bại / Lỗi</p>
          <p className="mt-1 text-2xl font-black text-rose-600">{failedCount}</p>
        </div>
      </div>

      {actionMessage && (
        <div
          className={`rounded-xl border p-3 text-xs font-semibold ${
            actionMessage.type === "success"
              ? "border-emerald-200 bg-emerald-50 text-emerald-800"
              : "border-rose-200 bg-rose-50 text-rose-800"
          }`}
        >
          {actionMessage.text}
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-xs font-medium text-rose-700">
          Lỗi: {error}
        </div>
      )}

      {/* Main Jobs Table / List */}
      <Card className="rounded-2xl border border-slate-200/90 bg-white p-0 shadow-sm overflow-hidden">
        {loading && jobs.length === 0 ? (
          <div className="flex items-center justify-center py-16 text-slate-400">
            <Spinner size={18} />
            <span className="ml-2.5 text-xs font-medium">Đang tải danh sách hàng đợi...</span>
          </div>
        ) : jobs.length === 0 ? (
          <div className="py-16 text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 text-slate-400">
              <IconFilm size={24} />
            </div>
            <p className="mt-3 text-sm font-bold text-slate-700">Hàng đợi đang trống</p>
            <p className="mt-1 text-xs text-slate-500 max-w-sm mx-auto">
              Khi Auto Publish và Lịch đăng (Schedule) được kích hoạt, hệ thống sẽ tự động quét video từ kho và đưa vào hàng đợi tại đây.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50/75 text-[11px] font-bold text-slate-600 uppercase tracking-wider">
                  <th className="py-3 px-4">Video / Nguồn</th>
                  <th className="py-3 px-4">Kênh YouTube</th>
                  <th className="py-3 px-4">Định dạng</th>
                  <th className="py-3 px-4">Lịch xuất bản (Giờ VN)</th>
                  <th className="py-3 px-4">Trạng thái</th>
                  <th className="py-3 px-4 text-right">Thao tác</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {jobs.map((job) => {
                  const isProcessing = job.status === "processing";
                  const isFailed = job.status === "failed";
                  const isDone = job.status === "done" || job.status === "published";
                  const isQueued = job.status === "queued";
                  const isCancelled = job.status === "cancelled";

                  return (
                    <tr key={job.id} className="hover:bg-slate-50/60 transition-colors">
                      {/* Video / Source */}
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-3">
                          <div className="relative h-12 w-9 shrink-0 overflow-hidden rounded-md bg-slate-100 border border-slate-200">
                            {job.thumbnail_url ? (
                              <Image
                                src={job.thumbnail_url}
                                alt="thumbnail"
                                fill
                                sizes="36px"
                                className="object-cover"
                                unoptimized
                              />
                            ) : (
                              <div className="flex h-full w-full items-center justify-center text-slate-300">
                                <IconFilm size={16} />
                              </div>
                            )}
                          </div>
                          <div className="min-w-0 max-w-xs">
                            <p className="truncate font-bold text-slate-900" title={job.reel_caption || ""}>
                              {job.reel_caption || `Video #${job.reel_db_id}`}
                            </p>
                            <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-slate-500">
                              <span className="font-semibold text-slate-700">@{job.source_username || "tiktok"}</span>
                              {job.reel_duration ? <span>· {Math.round(job.reel_duration)}s</span> : null}
                            </div>
                          </div>
                        </div>
                      </td>

                      {/* YouTube Destination */}
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2">
                          {job.destination_channel_avatar_url ? (
                            <Image
                              src={job.destination_channel_avatar_url}
                              alt="channel"
                              width={22}
                              height={22}
                              className="rounded-full border border-slate-200 shrink-0"
                              unoptimized
                            />
                          ) : (
                            <div className="h-5 w-5 rounded-full bg-rose-100 text-rose-600 flex items-center justify-center font-bold text-[10px] shrink-0">
                              YT
                            </div>
                          )}
                          <span className="truncate font-medium text-slate-800 text-xs max-w-[140px]">
                            {job.destination_channel_name || "Kênh mặc định"}
                          </span>
                        </div>
                      </td>

                      {/* Format */}
                      <td className="py-3 px-4">
                        <span className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-2 py-0.5 text-[11px] font-bold text-slate-700 uppercase">
                          {job.youtube_upload_mode === "shorts" ? "Shorts" : job.youtube_upload_mode === "video" ? "Video" : "Both"}
                        </span>
                      </td>

                      {/* Scheduled time */}
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-1.5 text-slate-700">
                          <IconClock size={13} className="text-slate-400 shrink-0" />
                          <span className="font-medium text-xs">
                            {formatDateTime(job.scheduled_at || job.queued_at)}
                          </span>
                        </div>
                      </td>

                      {/* Status */}
                      <td className="py-3 px-4">
                        <div>
                          {isProcessing && (
                            <span className="inline-flex items-center gap-1 rounded-full bg-indigo-50 px-2.5 py-0.5 text-[11px] font-bold text-indigo-700 border border-indigo-200 animate-pulse">
                              <Spinner size={12} />
                              Đang đăng ({job.stage || "processing"})
                            </span>
                          )}
                          {isQueued && (
                            <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2.5 py-0.5 text-[11px] font-bold text-amber-700 border border-amber-200">
                              Chờ đăng
                            </span>
                          )}
                          {isDone && (
                            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-0.5 text-[11px] font-bold text-emerald-700 border border-emerald-200">
                              <IconCheck size={11} />
                              Đã xuất bản
                            </span>
                          )}
                          {isFailed && (
                            <span className="inline-flex items-center gap-1 rounded-full bg-rose-50 px-2.5 py-0.5 text-[11px] font-bold text-rose-700 border border-rose-200" title={job.error || ""}>
                              <IconAlert size={11} />
                              Lỗi ({job.error_code || "FAILED"})
                            </span>
                          )}
                          {isCancelled && (
                            <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-0.5 text-[11px] font-semibold text-slate-600 border border-slate-200">
                              Đã hủy
                            </span>
                          )}

                          {job.error && (
                            <p className="mt-1 text-[11px] text-rose-600 truncate max-w-xs" title={job.error}>
                              {job.error}
                            </p>
                          )}
                        </div>
                      </td>

                      {/* Actions */}
                      <td className="py-3 px-4 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          <button
                            type="button"
                            onClick={() => setDetailJob(job)}
                            className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] font-semibold text-slate-600 hover:bg-slate-50 transition"
                          >
                            Chi tiết
                          </button>

                          {isFailed && (
                            <button
                              type="button"
                              disabled={actionJobId === job.id}
                              onClick={() => handleRetry(job.id)}
                              className="rounded-lg bg-indigo-600 px-2 py-1 text-[11px] font-bold text-white hover:bg-indigo-700 transition disabled:opacity-50"
                            >
                              {actionJobId === job.id ? <Spinner size={12} /> : "Thử lại"}
                            </button>
                          )}

                          {isQueued && (
                            <>
                              <button
                                type="button"
                                onClick={() => {
                                  setRescheduleJob(job);
                                  // Default input value formatted for datetime-local
                                  const d = job.scheduled_at ? new Date(job.scheduled_at) : new Date();
                                  setNewScheduleTime(d.toISOString().slice(0, 16));
                                }}
                                className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] font-semibold text-slate-700 hover:bg-slate-50 transition"
                              >
                                Đổi lịch
                              </button>
                              <button
                                type="button"
                                disabled={actionJobId === job.id}
                                onClick={() => handleCancel(job.id)}
                                className="rounded-lg border border-rose-200 bg-rose-50 px-2 py-1 text-[11px] font-bold text-rose-700 hover:bg-rose-100 transition disabled:opacity-50"
                              >
                                {actionJobId === job.id ? <Spinner size={12} /> : "Hủy"}
                              </button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Reschedule Modal */}
      {rescheduleJob && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-sm p-4">
          <div className="w-full max-w-md rounded-2xl bg-white p-5 shadow-2xl border border-slate-200">
            <h3 className="text-sm font-extrabold text-slate-900">Thay đổi thời gian đăng (Reschedule)</h3>
            <p className="mt-1 text-xs text-slate-500">
              Chọn thời điểm phát hành mới cho video <b>{rescheduleJob.reel_caption || rescheduleJob.id}</b>.
            </p>

            <form onSubmit={handleRescheduleSubmit} className="mt-4 space-y-3.5">
              <div>
                <label className="block text-xs font-semibold text-slate-700">Ngày giờ đăng mới (Giờ VN)</label>
                <input
                  type="datetime-local"
                  required
                  value={newScheduleTime}
                  onChange={(e) => setNewScheduleTime(e.target.value)}
                  className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-xs text-slate-900 focus:border-indigo-600 focus:outline-none focus:ring-1 focus:ring-indigo-600"
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setRescheduleJob(null)}
                  className="rounded-xl border border-slate-200 px-3.5 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                >
                  Đóng
                </button>
                <button
                  type="submit"
                  disabled={rescheduling}
                  className={`${btnPrimary} min-h-[36px] px-4 text-xs font-bold disabled:opacity-50`}
                >
                  {rescheduling ? <Spinner size={12} /> : "Cập nhật lịch"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Detail Modal */}
      {detailJob && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-sm p-4">
          <div className="w-full max-w-lg rounded-2xl bg-white p-5 shadow-2xl border border-slate-200 max-h-[85vh] flex flex-col">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-sm font-extrabold text-slate-900">Chi tiết lượt đăng #{detailJob.id}</h3>
              <button
                type="button"
                onClick={() => setDetailJob(null)}
                className="text-slate-400 hover:text-slate-600 text-sm font-bold"
              >
                ✕
              </button>
            </div>

            <div className="mt-4 overflow-y-auto space-y-3 text-xs text-slate-700 pr-1">
              <div className="grid grid-cols-2 gap-2 bg-slate-50 p-3 rounded-xl border border-slate-200/70">
                <div>
                  <span className="text-[11px] text-slate-500 font-medium">Job ID:</span>
                  <p className="font-mono font-bold text-slate-900 truncate">{detailJob.id}</p>
                </div>
                <div>
                  <span className="text-[11px] text-slate-500 font-medium">Publication ID:</span>
                  <p className="font-mono font-bold text-slate-900 truncate">{detailJob.publication_id}</p>
                </div>
                <div>
                  <span className="text-[11px] text-slate-500 font-medium">Trạng thái:</span>
                  <p className="font-bold text-slate-900 uppercase">{detailJob.status}</p>
                </div>
                <div>
                  <span className="text-[11px] text-slate-500 font-medium">Giai đoạn (Stage):</span>
                  <p className="font-semibold text-slate-900">{detailJob.stage || "—"}</p>
                </div>
                <div>
                  <span className="text-[11px] text-slate-500 font-medium">Định dạng:</span>
                  <p className="font-semibold text-slate-900 uppercase">{detailJob.youtube_upload_mode || "shorts"}</p>
                </div>
                <div>
                  <span className="text-[11px] text-slate-500 font-medium">YouTube Video ID:</span>
                  <p className="font-mono font-bold text-indigo-600">{detailJob.youtube_video_id || "Chưa có"}</p>
                </div>
              </div>

              {detailJob.shorts_check_note && (
                <div className="rounded-xl border border-slate-200 bg-white p-3">
                  <p className="text-[11px] font-bold text-slate-500">Kết quả kiểm tra Shorts (ffprobe):</p>
                  <p className="mt-1 font-medium text-slate-800">{detailJob.shorts_check_note}</p>
                </div>
              )}

              {detailJob.error && (
                <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-rose-800">
                  <p className="text-[11px] font-bold">Lỗi chi tiết ({detailJob.error_code || "ERROR"}):</p>
                  <p className="mt-1 font-mono text-[11px]">{detailJob.error}</p>
                </div>
              )}

              <div className="space-y-1.5 pt-2 border-t border-slate-100 text-[11px] text-slate-500">
                <p>Khởi tạo: {formatDateTime(detailJob.queued_at)}</p>
                {detailJob.started_at && <p>Bắt đầu: {formatDateTime(detailJob.started_at)}</p>}
                {detailJob.finished_at && <p>Hoàn thành: {formatDateTime(detailJob.finished_at)}</p>}
              </div>
            </div>

            <div className="mt-4 pt-3 border-t border-slate-100 flex justify-end">
              <button
                type="button"
                onClick={() => setDetailJob(null)}
                className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-bold text-slate-700 hover:bg-slate-50"
              >
                Đóng
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
