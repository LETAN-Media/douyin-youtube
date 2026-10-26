"use client";

import { useEffect, useState } from "react";
import { Badge, Card, CardHeader, Spinner, btnPrimary, btnSecondary, btnSmall, inputCls, labelCls } from "@/components/ui";
import { IconAlert, IconCheck, IconClock, IconFilm, IconPlay, IconRefresh, IconUpload, IconX } from "@/components/icons";
import type { TikTokScheduleDto, TikTokSchedulePreviewDto, TikTokScheduleStatusDto, TikTokSlotDto } from "@/lib/tiktok-api";

interface Props {
  pipelineId: string;
  initialSchedule: TikTokScheduleDto | null;
  initialSlots: TikTokSlotDto[];
}

const WEEKDAYS = [
  { id: 0, label: "Thứ 2" },
  { id: 1, label: "Thứ 3" },
  { id: 2, label: "Thứ 4" },
  { id: 3, label: "Thứ 5" },
  { id: 4, label: "Thứ 6" },
  { id: 5, label: "Thứ 7", isWeekend: true },
  { id: 6, label: "Chủ nhật", isWeekend: true },
];

const TIMEZONES = [
  { id: "Asia/Ho_Chi_Minh", label: "Asia/Ho_Chi_Minh (GMT+7)" },
  { id: "UTC", label: "UTC (GMT+0)" },
  { id: "Asia/Singapore", label: "Asia/Singapore (GMT+8)" },
  { id: "Asia/Tokyo", label: "Asia/Tokyo (GMT+9)" },
  { id: "America/New_York", label: "America/New_York (EST/EDT)" },
  { id: "America/Los_Angeles", label: "America/Los_Angeles (PST/PDT)" },
  { id: "Europe/London", label: "Europe/London (GMT/BST)" },
];

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString("vi-VN", {
      hour: "2-digit",
      minute: "2-digit",
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    });
  } catch {
    return iso;
  }
}

export function TikTokScheduler({ pipelineId, initialSchedule, initialSlots }: Props) {
  const [schedule, setSchedule] = useState<TikTokScheduleDto | null>(initialSchedule);
  const [slots, setSlots] = useState<TikTokSlotDto[]>(initialSlots);
  const [status, setStatus] = useState<TikTokScheduleStatusDto | null>(null);
  const [loadingStatus, setLoadingStatus] = useState(false);

  // Form states
  const [enabled, setEnabled] = useState(Boolean(initialSchedule?.enabled));
  const [timezone, setTimezone] = useState(initialSchedule?.timezone || "Asia/Ho_Chi_Minh");
  const [maxDaily, setMaxDaily] = useState(initialSchedule?.max_daily || 5);
  const [batchTime, setBatchTime] = useState(initialSchedule?.batch_time || "06:00");
  const [activeDays, setActiveDays] = useState<number[]>(
    Array.isArray(initialSchedule?.active_days) ? initialSchedule.active_days : [0, 1, 2, 3, 4, 5, 6]
  );
  const [weekendPriority, setWeekendPriority] = useState(Boolean(initialSchedule?.weekend_priority));
  const [videoOrder, setVideoOrder] = useState<"newest" | "oldest">(
    initialSchedule?.video_order === "oldest" ? "oldest" : "newest"
  );
  const [minInterval, setMinInterval] = useState(initialSchedule?.min_interval_minutes || 60);

  // Status & modal states
  const [saving, setSaving] = useState(false);
  const [runningBatch, setRunningBatch] = useState(false);
  const [confirmRunNowOpen, setConfirmRunNowOpen] = useState(false);
  const [generatingSlots, setGeneratingSlots] = useState(false);
  const [togglingEnabled, setTogglingEnabled] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  // Preview modal states
  const [previewModalOpen, setPreviewModalOpen] = useState(false);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [previewData, setPreviewData] = useState<TikTokSchedulePreviewDto | null>(null);

  async function loadStatus() {
    setLoadingStatus(true);
    try {
      const res = await fetch(`/api/tiktok/schedule?pipeline_id=${encodeURIComponent(pipelineId)}&action=status`);
      if (res.ok) {
        const data = await res.json();
        setStatus(data);
      }
    } catch {
      // Ignore background fetch error
    } finally {
      setLoadingStatus(false);
    }
  }

  useEffect(() => {
    if (initialSchedule) {
      setEnabled(Boolean(initialSchedule.enabled));
      setTimezone(initialSchedule.timezone || "Asia/Ho_Chi_Minh");
      setMaxDaily(initialSchedule.max_daily || 5);
      setBatchTime(initialSchedule.batch_time || "06:00");
      if (Array.isArray(initialSchedule.active_days)) {
        setActiveDays(initialSchedule.active_days);
      }
      setWeekendPriority(Boolean(initialSchedule.weekend_priority));
      setVideoOrder(initialSchedule.video_order === "oldest" ? "oldest" : "newest");
      setMinInterval(initialSchedule.min_interval_minutes || 60);
    }
    void loadStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialSchedule, pipelineId]);

  async function handleToggleEnabled() {
    if (togglingEnabled) return;
    setTogglingEnabled(true);
    setMessage(null);
    const nextState = !enabled;
    try {
      const res = await fetch("/api/tiktok/schedule", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pipeline_id: pipelineId, enabled: nextState }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.message || data.error || "Không thể bật/tắt lịch đăng.");
      }
      setEnabled(nextState);
      setSchedule((prev) => (prev ? { ...prev, enabled: nextState } : null));
      setMessage({
        type: "success",
        text: nextState
          ? "Đã kích hoạt Lịch đăng tự động cho Pipeline."
          : "Đã tạm dừng Lịch đăng tự động cho Pipeline.",
      });
      void loadStatus();
    } catch (err: unknown) {
      setMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Lỗi khi cập nhật trạng thái lịch.",
      });
    } finally {
      setTogglingEnabled(false);
    }
  }

  function handleDayToggle(dayId: number) {
    setActiveDays((prev) =>
      prev.includes(dayId) ? prev.filter((d) => d !== dayId) : [...prev, dayId].sort()
    );
  }

  async function handleSaveSettings(e: React.FormEvent) {
    e.preventDefault();
    if (saving) return;

    const numDaily = Number(maxDaily);
    if (!Number.isFinite(numDaily) || numDaily < 1 || numDaily > 10) {
      setMessage({
        type: "error",
        text: "Số video đăng trong ngày phải nằm trong khoảng từ 1 đến 10.",
      });
      return;
    }

    setSaving(true);
    setMessage(null);
    try {
      const res = await fetch("/api/tiktok/schedule", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pipeline_id: pipelineId,
          action: "update_settings",
          settings: {
            timezone,
            max_daily: numDaily,
            batch_time: batchTime,
            active_days: activeDays,
            weekend_priority: weekendPriority,
            video_order: videoOrder,
            min_interval_minutes: Number(minInterval),
          },
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.message || data.error || "Không thể lưu cài đặt lịch.");
      }
      setSchedule(data);
      setMessage({ type: "success", text: "Đã lưu cài đặt lịch đăng thành công." });
      void loadStatus();
    } catch (err: unknown) {
      setMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Lỗi khi lưu cài đặt.",
      });
    } finally {
      setSaving(false);
    }
  }

  async function handleOpenPreview() {
    setLoadingPreview(true);
    setPreviewModalOpen(true);
    setMessage(null);
    try {
      const res = await fetch(`/api/tiktok/schedule?pipeline_id=${encodeURIComponent(pipelineId)}&action=preview`);
      const data = await res.json();
      setPreviewData(data);
    } catch {
      setPreviewData({
        ok: false,
        dry_run: true,
        target_date: "",
        is_lookahead: false,
        planned_count: 0,
        planned_slots: [],
        daily_limit: maxDaily,
        destination_name: "",
        message: "Lỗi kết nối khi tải xem trước lịch.",
      });
    } finally {
      setLoadingPreview(false);
    }
  }

  async function executeRunBatchNow() {
    if (runningBatch) return;
    setRunningBatch(true);
    setConfirmRunNowOpen(false);
    setMessage(null);
    try {
      const res = await fetch("/api/tiktok/schedule", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pipeline_id: pipelineId,
          action: "run_now",
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.message || data.error || "Không thể chạy lịch đăng.");
      }
      if (data.ok) {
        setMessage({
          type: "success",
          text: data.message || `Đã lên lịch thành công ${data.videos_enqueued} video vào hàng đợi.`,
        });
      } else {
        setMessage({
          type: "error",
          text: data.message || `Không thể lên lịch: ${data.reason}`,
        });
      }
      void loadStatus();
      // Refresh slots
      const sRes = await fetch(`/api/tiktok/schedule?pipeline_id=${encodeURIComponent(pipelineId)}`);
      if (sRes.ok) {
        const sData = await sRes.json();
        if (sData.slots) setSlots(sData.slots);
      }
    } catch (err: unknown) {
      setMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Lỗi khi kích hoạt chạy lịch.",
      });
    } finally {
      setRunningBatch(false);
    }
  }

  async function handleGenerateSlots() {
    if (generatingSlots) return;
    setGeneratingSlots(true);
    setMessage(null);
    try {
      const res = await fetch("/api/tiktok/schedule", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pipeline_id: pipelineId,
          action: "generate_slots",
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.message || data.error || "Không thể tạo khung giờ.");
      }
      if (Array.isArray(data.slots)) {
        setSlots(data.slots);
      }
      setMessage({ type: "success", text: "Đã tái tạo khung giờ đăng cho toàn bộ tuần (hỗ trợ phút lẻ)." });
      // Refresh slots from server
      const sRes = await fetch(`/api/tiktok/schedule?pipeline_id=${encodeURIComponent(pipelineId)}`);
      if (sRes.ok) {
        const sData = await sRes.json();
        if (sData.slots) setSlots(sData.slots);
      }
      void loadStatus();
    } catch (err: unknown) {
      setMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Lỗi khi tạo khung giờ.",
      });
    } finally {
      setGeneratingSlots(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* Top Banner & Quick Trigger */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between rounded-2xl border border-slate-200/90 bg-white p-5 shadow-sm sm:p-6">
        <div>
          <div className="flex items-center gap-2.5">
            <h2 className="text-lg font-extrabold text-slate-900 sm:text-xl">Lịch xuất bản tự động (Schedule)</h2>
            <span
              className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-bold border ${
                enabled
                  ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                  : "bg-slate-100 text-slate-600 border-slate-200"
              }`}
            >
              {enabled ? "LỊCH ĐANG BẬT" : "LỊCH ĐANG TẮT"}
            </span>
          </div>
          <p className="mt-1 text-xs text-slate-500">
            Tự động lấy video từ kho, tạo SEO và phân bổ vào các khung giờ vàng trong ngày.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2.5 self-start sm:self-auto">
          <button
            type="button"
            disabled={togglingEnabled}
            onClick={handleToggleEnabled}
            className={`min-h-[40px] px-4 rounded-xl text-xs font-bold transition shadow-sm ${
              enabled
                ? "border border-amber-300 bg-amber-50 text-amber-800 hover:bg-amber-100"
                : "bg-emerald-600 text-white hover:bg-emerald-700"
            }`}
          >
            {togglingEnabled ? <Spinner size={14} /> : enabled ? "Tắt lịch đăng" : "Bật lịch đăng"}
          </button>

          <button
            type="button"
            disabled={loadingPreview}
            onClick={handleOpenPreview}
            className={`${btnSecondary} min-h-[40px] px-4 text-xs font-bold shadow-sm inline-flex items-center gap-1.5`}
          >
            {loadingPreview ? <Spinner size={14} /> : <IconFilm size={14} />}
            Xem trước lịch (Preview)
          </button>

          <button
            type="button"
            disabled={runningBatch}
            onClick={() => setConfirmRunNowOpen(true)}
            className={`${btnPrimary} min-h-[40px] px-4 text-xs font-bold shadow-sm inline-flex items-center gap-1.5`}
          >
            {runningBatch ? <Spinner size={14} /> : <IconPlay size={14} />}
            Tạo lịch ngay (Run Batch Now)
          </button>
        </div>
      </div>

      {/* Operational Status Card */}
      <Card className="rounded-2xl border border-slate-200/90 bg-white p-5 shadow-sm sm:p-6">
        <div className="flex items-center justify-between border-b border-slate-100 pb-4">
          <div>
            <h3 className="text-sm font-extrabold text-slate-900 flex items-center gap-2">
              <IconClock size={16} />
              Trạng thái vận hành Scheduler & Publisher
            </h3>
            <p className="mt-0.5 text-xs text-slate-500">
              Kiểm tra trực tiếp tiến độ batch, worker heartbeat và hàng đợi xuất bản
            </p>
          </div>
          <button
            type="button"
            onClick={() => void loadStatus()}
            disabled={loadingStatus}
            className={btnSmall}
            title="Làm mới trạng thái"
          >
            {loadingStatus ? <Spinner size={14} /> : <IconRefresh size={14} />}
          </button>
        </div>

        {/* 6 Metric Grid */}
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
            <span className="text-[11px] font-semibold text-slate-500">Giờ chạy batch tới</span>
            <p className="mt-1 font-extrabold text-slate-900 text-xs">
              {status?.next_scheduled_run ? formatDateTime(status.next_scheduled_run) : "—"}
            </p>
          </div>

          <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
            <span className="text-[11px] font-semibold text-slate-500">Lần chạy gần nhất</span>
            <p className="mt-1 font-extrabold text-slate-900 text-xs">
              {status?.last_scheduler_run ? formatDateTime(status.last_scheduler_run) : "Chưa có"}
            </p>
          </div>

          <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
            <span className="text-[11px] font-semibold text-slate-500">Kết quả chạy gần nhất</span>
            <p className="mt-1 font-bold text-slate-800 text-xs truncate" title={status?.last_scheduler_result?.message || ""}>
              {status?.last_scheduler_result?.ok ? (
                <span className="text-emerald-700">Thành công ({status.last_scheduler_result.videos_enqueued} video)</span>
              ) : status?.last_scheduler_result ? (
                <span className="text-amber-700">{status.last_scheduler_result.reason || "Chờ xử lý"}</span>
              ) : (
                "Chưa có"
              )}
            </p>
          </div>

          <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
            <span className="text-[11px] font-semibold text-slate-500">Giờ đăng video tiếp theo</span>
            <p className="mt-1 font-extrabold text-indigo-700 text-xs">
              {status?.next_publishing_time ? formatDateTime(status.next_publishing_time) : "Chưa có video"}
            </p>
          </div>

          <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
            <span className="text-[11px] font-semibold text-slate-500">Video đủ điều kiện kho</span>
            <p className="mt-1 font-extrabold text-slate-900 text-xs">
              {status?.eligible_inventory !== undefined ? `${status.eligible_inventory} video` : "—"}
            </p>
          </div>

          <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
            <span className="text-[11px] font-semibold text-slate-500">Hàng đợi xuất bản</span>
            <p className="mt-1 font-extrabold text-slate-900 text-xs">
              {status?.scheduled_jobs !== undefined ? `${status.scheduled_jobs} chờ đăng` : "—"}
            </p>
          </div>
        </div>

        {/* Worker Status Indicators & Reason Banner */}
        <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between rounded-xl bg-slate-50 p-3.5 border border-slate-200/80">
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5 text-xs font-bold">
              <span>Scheduler:</span>
              <span
                className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-extrabold ${
                  status?.scheduler_worker_online
                    ? "bg-emerald-100 text-emerald-800"
                    : "bg-rose-100 text-rose-800"
                }`}
              >
                {status?.scheduler_worker_online ? "🟢 Online" : "🔴 Offline"}
              </span>
            </div>

            <div className="ml-3 flex items-center gap-1.5 text-xs font-bold">
              <span>Publisher:</span>
              <span
                className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-extrabold ${
                  status?.publisher_status === "running"
                    ? "bg-indigo-100 text-indigo-800"
                    : status?.publisher_status === "idle"
                    ? "bg-emerald-100 text-emerald-800"
                    : "bg-rose-100 text-rose-800"
                }`}
              >
                {status?.publisher_status === "running"
                  ? "🔵 Đang xử lý"
                  : status?.publisher_status === "idle"
                  ? "🟢 Chờ việc (Idle)"
                  : "🔴 Offline"}
              </span>
            </div>
          </div>

          <div className="text-xs text-slate-700 font-semibold flex items-center gap-1.5">
            <span className="text-slate-400">Trạng thái:</span>
            <span className="text-indigo-800 bg-white px-2 py-1 rounded-md border border-slate-200/80">
              {status?.reason_message || "Đang kiểm tra trạng thái..."}
            </span>
          </div>
        </div>
      </Card>

      {message && (
        <div
          className={`rounded-xl border p-3.5 text-xs font-semibold ${
            message.type === "success"
              ? "border-emerald-200 bg-emerald-50 text-emerald-800"
              : "border-rose-200 bg-rose-50 text-rose-800"
          }`}
        >
          {message.text}
        </div>
      )}

      {/* Main Settings Form */}
      <form onSubmit={handleSaveSettings} className="space-y-6">
        <Card className="rounded-2xl border border-slate-200/90 bg-white p-5 shadow-sm sm:p-6">
          <CardHeader
            title="Cấu hình quy tắc lên lịch"
            subtitle="Thiết lập giới hạn số lượng video, múi giờ và tần suất xuất bản"
          />

          <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-3">
            {/* Timezone */}
            <div>
              <label className={labelCls}>Múi giờ phát hành</label>
              <select
                value={timezone}
                onChange={(e) => setTimezone(e.target.value)}
                className={`${inputCls} mt-1`}
              >
                {TIMEZONES.map((tz) => (
                  <option key={tz.id} value={tz.id}>
                    {tz.label}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-[11px] text-slate-500">Mặc định: Asia/Ho_Chi_Minh (GMT+7)</p>
            </div>

            {/* Max Daily */}
            <div>
              <label className={labelCls}>Số video tối đa mỗi ngày</label>
              <input
                type="number"
                min={1}
                max={10}
                value={maxDaily}
                onChange={(e) => setMaxDaily(Number(e.target.value))}
                className={`${inputCls} mt-1`}
                required
              />
              <p className="mt-1 text-[11px] text-slate-500">Giới hạn số lượng video đăng mỗi ngày (tối thiểu 1, tối đa 10 video)</p>
            </div>

            {/* Batch execution time */}
            <div>
              <label className={labelCls}>Giờ bắt đầu chạy lô (Batch Time)</label>
              <input
                type="time"
                value={batchTime}
                onChange={(e) => setBatchTime(e.target.value)}
                className={`${inputCls} mt-1`}
                required
              />
              <p className="mt-1 text-[11px] text-slate-500">Thời điểm scheduler tự động phân bổ slot cho ngày</p>
            </div>
          </div>

          <div className="mt-5 pt-5 border-t border-slate-100 grid grid-cols-1 gap-5 sm:grid-cols-2">
            {/* Active Days */}
            <div>
              <label className={labelCls}>Ngày trong tuần xuất bản</label>
              <div className="mt-2 flex flex-wrap gap-2">
                {WEEKDAYS.map((w) => {
                  const isChecked = activeDays.includes(w.id);
                  return (
                    <button
                      key={w.id}
                      type="button"
                      onClick={() => handleDayToggle(w.id)}
                      className={`min-h-[34px] px-3 rounded-lg text-xs font-bold border transition ${
                        isChecked
                          ? "border-indigo-600 bg-indigo-50 text-indigo-700 ring-1 ring-indigo-600"
                          : "border-slate-200 bg-slate-50 text-slate-400 hover:text-slate-600"
                      }`}
                    >
                      {w.label}
                    </button>
                  );
                })}
              </div>
              <p className="mt-1.5 text-[11px] text-slate-500">Chỉ tự động lên lịch vào những ngày được chọn</p>
            </div>

            {/* Weekend Priority & Ordering */}
            <div className="space-y-4">
              <div>
                <label className={labelCls}>Thứ tự lấy video trong kho</label>
                <div className="mt-2 grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => setVideoOrder("newest")}
                    className={`min-h-[36px] rounded-lg border text-xs font-bold transition px-3 ${
                      videoOrder === "newest"
                        ? "border-indigo-600 bg-indigo-50 text-indigo-700 ring-1 ring-indigo-600"
                        : "border-slate-200 bg-white text-slate-600"
                    }`}
                  >
                    Mới nhất trước (Newest)
                  </button>
                  <button
                    type="button"
                    onClick={() => setVideoOrder("oldest")}
                    className={`min-h-[36px] rounded-lg border text-xs font-bold transition px-3 ${
                      videoOrder === "oldest"
                        ? "border-indigo-600 bg-indigo-50 text-indigo-700 ring-1 ring-indigo-600"
                        : "border-slate-200 bg-white text-slate-600"
                    }`}
                  >
                    Cũ nhất trước (Oldest)
                  </button>
                </div>
              </div>

              <div className="flex items-center justify-between rounded-xl border border-slate-200 p-3 bg-slate-50/50">
                <div>
                  <p className="text-xs font-bold text-slate-800">Ưu tiên thứ Bảy & Chủ nhật</p>
                  <p className="text-[11px] text-slate-500">Tự động tăng cường khung giờ vào cuối tuần</p>
                </div>
                <input
                  type="checkbox"
                  checked={weekendPriority}
                  onChange={(e) => setWeekendPriority(e.target.checked)}
                  className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                />
              </div>

              <div>
                <label className={labelCls}>Khoảng cách tối thiểu giữa 2 lần đăng</label>
                <div className="mt-1 flex items-center gap-2">
                  <input
                    type="number"
                    min={5}
                    max={360}
                    value={minInterval}
                    onChange={(e) => setMinInterval(Number(e.target.value))}
                    className={`${inputCls} w-28`}
                  />
                  <span className="text-xs text-slate-600 font-medium">phút</span>
                </div>
              </div>
            </div>
          </div>

          <div className="mt-6 flex justify-end border-t border-slate-100 pt-4">
            <button
              type="submit"
              disabled={saving}
              className={`${btnPrimary} min-h-[38px] px-5 text-xs font-bold shadow-sm`}
            >
              {saving ? <Spinner size={14} /> : "Lưu cấu hình lịch"}
            </button>
          </div>
        </Card>
      </form>

      {/* Slots Section */}
      <Card className="rounded-2xl border border-slate-200/90 bg-white p-5 shadow-sm sm:p-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between border-b border-slate-100 pb-4">
          <div>
            <h3 className="text-sm font-extrabold text-slate-900">Khung giờ phát hành tuần (Publish Slots)</h3>
            <p className="mt-0.5 text-xs text-slate-500">
              Các mốc thời gian đăng video được phân bổ đều trong ngày (hỗ trợ phút lẻ chính xác)
            </p>
          </div>
          <button
            type="button"
            disabled={generatingSlots}
            onClick={handleGenerateSlots}
            className={`${btnSecondary} min-h-[36px] px-3.5 text-xs font-bold self-start sm:self-auto`}
          >
            {generatingSlots ? <Spinner size={14} /> : "Tạo lại khung giờ tuần"}
          </button>
        </div>

        {slots.length === 0 ? (
          <div className="py-12 text-center text-xs text-slate-500">
            Chưa có khung giờ đăng nào được tạo. Bấm &quot;Tạo lại khung giờ tuần&quot; để xếp lịch.
          </div>
        ) : (
          <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4 md:grid-cols-7">
            {WEEKDAYS.map((wd) => {
              const daySlots = slots.filter((s) => s.weekday === wd.id && s.enabled);
              const isActive = activeDays.includes(wd.id);
              return (
                <div
                  key={wd.id}
                  className={`rounded-xl border p-3 ${
                    isActive ? "border-slate-200 bg-white" : "border-slate-100 bg-slate-50 opacity-60"
                  }`}
                >
                  <p className="text-xs font-bold text-slate-800">{wd.label}</p>
                  <p className="text-[11px] text-slate-500">{daySlots.length} slot</p>
                  <div className="mt-2 space-y-1">
                    {daySlots.slice(0, 6).map((s) => (
                      <div
                        key={s.id || `${wd.id}-${s.slot_time}`}
                        className="rounded-md bg-slate-100 px-2 py-0.5 text-center text-[11px] font-mono font-medium text-slate-700"
                      >
                        {s.slot_time}
                      </div>
                    ))}
                    {daySlots.length > 6 && (
                      <p className="text-center text-[10px] text-slate-400">+{daySlots.length - 6} nữa</p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      {/* Preview Schedule Modal */}
      {previewModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-sm p-4 animate-fadeIn">
          <div className="w-full max-w-2xl rounded-2xl bg-white p-6 shadow-2xl border border-slate-200 max-h-[90vh] flex flex-col">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2">
                <IconFilm size={20} className="text-indigo-600" />
                <h3 className="text-base font-extrabold text-slate-900">Xem trước lịch phát hành (Schedule Preview)</h3>
              </div>
              <button
                type="button"
                onClick={() => setPreviewModalOpen(false)}
                className="text-slate-400 hover:text-slate-600 text-lg font-bold"
              >
                ✕
              </button>
            </div>

            <div className="mt-4 flex-1 overflow-y-auto space-y-4">
              {loadingPreview ? (
                <div className="py-16 text-center text-xs text-slate-500 flex items-center justify-center gap-2">
                  <Spinner size={16} />
                  <span>Đang tính toán lịch phát hành dự kiến...</span>
                </div>
              ) : previewData?.ok ? (
                <>
                  <div className="rounded-xl bg-indigo-50 border border-indigo-100 p-4 text-xs">
                    <p className="font-extrabold text-indigo-900">{previewData.message}</p>
                    <div className="mt-2 flex flex-wrap gap-4 text-[11px] text-indigo-700">
                      <span>Kênh: <b>{previewData.destination_name}</b></span>
                      <span>Ngày mục tiêu: <b>{previewData.target_date}</b></span>
                      <span>Giới hạn: <b>{previewData.daily_limit} video/ngày</b></span>
                      <span>Số slot dự kiến: <b>{previewData.planned_count}</b></span>
                    </div>
                  </div>

                  {previewData.planned_slots.length === 0 ? (
                    <div className="py-8 text-center text-xs text-slate-500">
                      Không có khung giờ nào khả dụng để xếp lịch cho ngày này.
                    </div>
                  ) : (
                    <div className="divide-y divide-slate-100 border border-slate-200 rounded-xl overflow-hidden">
                      {previewData.planned_slots.map((item, idx) => (
                        <div key={idx} className="flex items-center gap-3 p-3 hover:bg-slate-50/50">
                          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-slate-100 text-slate-600 text-xs font-bold">
                            {idx + 1}
                          </span>
                          {item.thumbnail_url ? (
                            // eslint-disable-next-line @next/next/no-img-element
                            <img
                              src={item.thumbnail_url}
                              alt=""
                              className="h-12 w-9 rounded object-cover shadow-sm bg-slate-100"
                            />
                          ) : (
                            <div className="h-12 w-9 rounded bg-slate-100 flex items-center justify-center text-slate-400 text-xs">
                              Video
                            </div>
                          )}
                          <div className="flex-1 min-w-0">
                            <p className="text-xs font-bold text-slate-900 truncate">
                              {item.caption}
                            </p>
                            <p className="text-[11px] text-slate-500">
                              ID: {item.reel_id} {item.duration ? `· ${item.duration}s` : ""}
                            </p>
                          </div>
                          <div className="text-right whitespace-nowrap">
                            <span className="rounded-lg bg-indigo-50 border border-indigo-200 px-2.5 py-1 text-xs font-bold text-indigo-700 font-mono">
                              {item.slot_time}
                            </span>
                            <p className="text-[10px] text-slate-400 mt-0.5">{item.scheduled_local}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              ) : (
                <div className="rounded-xl bg-amber-50 border border-amber-200 p-4 text-xs text-amber-800">
                  <p className="font-bold">Không thể tạo xem trước lịch:</p>
                  <p className="mt-1">{previewData?.message || previewData?.reason || "Vui lòng kiểm tra lại cấu hình."}</p>
                </div>
              )}
            </div>

            <div className="mt-4 pt-3 border-t border-slate-100 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setPreviewModalOpen(false)}
                className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
              >
                Đóng
              </button>
              {previewData?.ok && previewData.planned_count > 0 && (
                <button
                  type="button"
                  onClick={() => {
                    setPreviewModalOpen(false);
                    setConfirmRunNowOpen(true);
                  }}
                  className={`${btnPrimary} text-xs py-2 px-4`}
                >
                  Tạo lịch theo kế hoạch này
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Confirmation Modal for Run Batch Now */}
      {confirmRunNowOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-sm p-4 animate-fadeIn">
          <div className="w-full max-w-md rounded-2xl bg-white p-5 shadow-2xl border border-slate-200">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-indigo-600">
                <IconPlay size={20} />
              </div>
              <div>
                <h3 className="text-sm font-extrabold text-slate-900">Xác nhận tạo lịch ngay (Run Batch Now)</h3>
                <p className="mt-0.5 text-xs text-slate-500">
                  Phân bổ video vào các slot theo giới hạn hiện tại
                </p>
              </div>
            </div>

            <div className="mt-4 rounded-xl bg-slate-50 p-3.5 text-xs text-slate-600 leading-relaxed border border-slate-200/80">
              <p>
                Hệ thống sẽ quét các video đủ điều kiện trong kho và đưa vào hàng đợi xuất bản với các khung giờ phát hành đã thiết lập.
              </p>
              <ul className="mt-2 list-disc list-inside space-y-1 text-[11px] text-slate-500 font-medium">
                <li>Tối đa <b>{maxDaily} video</b> theo giới hạn hàng ngày.</li>
                <li>Video <b>KHÔNG được đăng ngay lập tức</b> lên YouTube.</li>
                <li>Publisher worker sẽ tự động xuất bản khi mốc giờ phát hành tới hạn.</li>
              </ul>
            </div>

            <div className="flex items-center justify-end gap-2.5 pt-4 mt-2 border-t border-slate-100">
              <button
                type="button"
                disabled={runningBatch}
                onClick={() => setConfirmRunNowOpen(false)}
                className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
              >
                Hủy
              </button>
              <button
                type="button"
                disabled={runningBatch}
                onClick={executeRunBatchNow}
                className="inline-flex min-h-[38px] items-center gap-1.5 rounded-xl bg-indigo-600 px-4 py-2 text-xs font-bold text-white shadow-sm hover:bg-indigo-700 transition disabled:opacity-50"
              >
                {runningBatch ? <Spinner size={14} /> : <IconPlay size={14} />}
                <span>Xác nhận tạo lịch</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
