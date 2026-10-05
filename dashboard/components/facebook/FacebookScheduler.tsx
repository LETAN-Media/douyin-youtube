"use client";

import { useState, useCallback } from "react";
import { Card, CardHeader, Badge, btnSmall, inputCls, labelCls } from "@/components/ui";
import { IconCalendar, IconCheck, IconPlay, IconClock } from "@/components/icons";
import type { FacebookScheduleStatus, FacebookScheduleDto, UpdateFacebookScheduleDto } from "@/lib/facebook-api";

const WEEKDAY_NAMES = ["Chủ nhật", "Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7"];
const WEEKDAY_KEYS = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];

const DEFAULT_SLOTS: Record<string, string[]> = {
  monday: ["11:30", "14:30", "18:30", "20:30", "22:30"],
  tuesday: ["11:30", "14:30", "18:30", "20:30", "22:30"],
  wednesday: ["11:30", "14:30", "18:30", "20:30", "22:30"],
  thursday: ["11:30", "14:30", "18:30", "20:30", "22:30"],
  friday: ["11:30", "14:30", "18:30", "20:30", "22:30"],
  saturday: ["09:30", "11:30", "15:00", "19:30", "21:30"],
  sunday: ["09:00", "11:00", "15:30", "19:00", "21:00"],
};

const TIMEZONE_OPTIONS = [
  { value: "Asia/Ho_Chi_Minh", label: "Asia/Ho_Chi_Minh (UTC+7)" },
  { value: "Asia/Bangkok", label: "Asia/Bangkok (UTC+7)" },
  { value: "UTC", label: "UTC" },
];

const MAX_DAILY_OPTIONS = [
  { value: "1", label: "1" },
  { value: "2", label: "2" },
  { value: "3", label: "3" },
  { value: "4", label: "4" },
  { value: "5", label: "5" },
];

async function fetchSchedule(pipelineId: string): Promise<FacebookScheduleDto> {
  const res = await fetch(`/api/facebook/scheduler/${encodeURIComponent(pipelineId)}`, {
    cache: "no-store",
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || `HTTP ${res.status}`);
  }
  return res.json();
}

async function saveSchedule(pipelineId: string, payload: UpdateFacebookScheduleDto): Promise<FacebookScheduleDto> {
  const res = await fetch(`/api/facebook/scheduler/${encodeURIComponent(pipelineId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || `HTTP ${res.status}`);
  }
  return res.json();
}

async function runBatch(pipelineId: string, destinationId: string): Promise<{
  ok: boolean;
  batch_id: string | null;
  status: string;
  videos_enqueued: number;
  reason: string | null;
  message: string;
}> {
  const res = await fetch(`/api/facebook/scheduler/${encodeURIComponent(pipelineId)}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ destinationId }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || `HTTP ${res.status}`);
  }
  return res.json();
}

export function FacebookScheduler({
  pipelineId,
  initialSchedule,
  initialStatus,
  destinationId,
}: {
  pipelineId: string;
  initialSchedule: FacebookScheduleDto | null;
  initialStatus: FacebookScheduleStatus;
  destinationId: string | null;
}) {
  const [schedule, setSchedule] = useState<FacebookScheduleDto | null>(initialSchedule);
  const [status, setStatus] = useState<FacebookScheduleStatus>(initialStatus);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [runningBatch, setRunningBatch] = useState(false);
  const [showRunConfirm, setShowRunConfirm] = useState(false);
  const [runResult, setRunResult] = useState<string | null>(null);

  const scheduleRef = schedule || {
    id: "",
    pipeline_id: pipelineId,
    timezone: "Asia/Ho_Chi_Minh",
    enabled: false, // Default false, will be overridden by user when creating
    max_daily_publish: 5,
    batch_time: "06:00",
    slots: DEFAULT_SLOTS,
    created_at: null,
    updated_at: null,
  };

  const handleSave = useCallback(async () => {
    // Allow saving even when schedule is null (creating new)
    const toSave = schedule || scheduleRef;
    setSaving(true);
    try {
      const payload: UpdateFacebookScheduleDto = {
        enabled: toSave.enabled,
        timezone: toSave.timezone,
        max_daily_publish: toSave.max_daily_publish,
        batch_time: toSave.batch_time,
        slots: toSave.slots,
      };
      const updated = await saveSchedule(pipelineId, payload);
      setSchedule(updated);
      setEditing(false);
      setRunResult("Đã lưu lịch thành công");
      setTimeout(() => setRunResult(null), 3000);
    } catch (err: any) {
      setRunResult(`Lỗi: ${err.message || "Không thể lưu lịch"}`);
      setTimeout(() => setRunResult(null), 5000);
    } finally {
      setSaving(false);
    }
  }, [pipelineId, schedule]);

  const handleRunBatch = useCallback(async () => {
    if (!destinationId) return;
    setRunningBatch(true);
    try {
      const result = await runBatch(pipelineId, destinationId);
      if (result.videos_enqueued > 0 && !result.reason) {
        setRunResult(`Đã xếp ${result.videos_enqueued} video vào hàng đợi`);
        setTimeout(() => setRunResult(null), 5000);
      } else {
        setRunResult(result.message || "Không có video nào được xếp vào hàng đợi");
        setTimeout(() => setRunResult(null), 8000);
      }
      setShowRunConfirm(false);
      // Refresh counters so the UI reflects any newly queued work.
      try {
        const fresh = await fetch(`/api/facebook/scheduler/${encodeURIComponent(pipelineId)}`);
        if (fresh.ok) {
          const data = await fresh.json().catch(() => null);
          if (data?.status) setStatus(data.status);
        }
      } catch {
        // Non-fatal: the batch result above is the source of truth.
      }
    } catch (err: any) {
      setRunResult(`Lỗi: ${err.message || "Không thể chạy batch"}`);
      setTimeout(() => setRunResult(null), 5000);
    } finally {
      setRunningBatch(false);
    }
  }, [pipelineId, destinationId]);

  const handleSlotChange = (dayKey: string, times: string[]) => {
    setSchedule(prev => prev ? { ...prev, slots: { ...prev.slots, [dayKey]: times } } : null);
  };

  const handleAddSlot = (dayKey: string) => {
    const current = scheduleRef.slots[dayKey] || [];
    if (current.length >= 5) return;
    const newTime = "00:00";
    handleSlotChange(dayKey, [...current, newTime]);
  };

  const handleRemoveSlot = (dayKey: string, index: number) => {
    const current = scheduleRef.slots[dayKey] || [];
    handleSlotChange(dayKey, current.filter((_, i) => i !== index));
  };

  const handleTimeChange = (dayKey: string, index: number, value: string) => {
    const current = scheduleRef.slots[dayKey] || [];
    const updated = [...current];
    updated[index] = value;
    handleSlotChange(dayKey, updated);
  };

  const batchStatus = status?.batch_status || "idle";
  const scheduledToday = status?.scheduled_today ?? 0;
  const dailyLimit = status?.daily_limit ?? 5;
  const slots = status?.slots || [];
  const invTotal = status?.inventory_total ?? null;
  const aiReady = status?.ai_ready ?? null;
  const aiGenerated = status?.ai_generated ?? 0;
  const aiPending = status?.ai_pending ?? 0;

  const slotsByDay = slots.reduce<Record<number, any[]>>((acc, slot: any) => {
    const day = slot.weekday ?? 0;
    acc[day] = acc[day] || [];
    acc[day].push(slot);
    return acc;
  }, {});

  return (
    <Card>
      <CardHeader
        title="Scheduler"
        subtitle="Lịch tự động đăng YouTube"
        icon={<IconCalendar size={16} />}
      />
      <div className="space-y-4 p-4 sm:px-5">
        {!editing ? (
          <> 
            <div className="flex flex-wrap items-center gap-3">
              <Badge tone={scheduleRef.enabled ? "green" : "slate"}>
                {scheduleRef.enabled ? "Auto ON" : "Auto OFF"}
              </Badge>
              <span className="text-xs text-slate-500">
                Timezone: {scheduleRef.timezone || "Asia/Ho_Chi_Minh"}
              </span>
              <span className="text-xs text-slate-500">
                Batch: {scheduleRef.batch_time || "06:00"}
              </span>
              <span className="text-xs text-slate-500">
                Max/day: {scheduleRef.max_daily_publish}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-center">
                <p className="text-xs text-slate-500">Hôm nay</p>
                <p className="text-sm font-bold text-slate-900">
                  {WEEKDAY_NAMES[status?.weekday ?? 0]}
                </p>
              </div>
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-center">
                <p className="text-xs text-slate-500">Batch</p>
                <p className="text-sm font-bold text-slate-900">
                  <Badge tone={
                    batchStatus === "completed" ? "green" :
                    batchStatus === "running" ? "amber" :
                    batchStatus === "failed" ? "red" :
                    "slate"
                  }>
                    {batchStatus}
                  </Badge>
                </p>
              </div>
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-center">
                <p className="text-xs text-slate-500">Scheduled</p>
                <p className="text-sm font-bold text-slate-900">
                  {scheduledToday}/{dailyLimit}
                </p>
              </div>
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-center">
                <p className="text-xs text-slate-500">Next batch</p>
                <p className="text-sm font-bold text-slate-900">
                  {status?.next_batch_at
                    ? new Date(status.next_batch_at).toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" })
                    : "—"}
                </p>
              </div>
            </div>

            {invTotal !== null && aiReady !== null ? (
              <div
                className={`rounded-xl border p-3 text-xs leading-relaxed ${
                  aiReady > 0
                    ? "border-indigo-200 bg-indigo-50 text-indigo-800"
                    : aiGenerated > 0
                      ? "border-amber-200 bg-amber-50 text-amber-800"
                      : "border-slate-200 bg-slate-50 text-slate-600"
                }`}
              >
                {aiReady > 0 ? (
                  <>Scheduler: {aiReady}/{dailyLimit} video AI-ready{invTotal > 0 ? ` · ${invTotal} video trong Inventory` : ""}</>
                ) : aiGenerated > 0 ? (
                  <>{invTotal} video trong Inventory · 0 video đã có AI metadata sẵn sàng (khớp cấu hình hiện tại) — AI cần xử lý lại.</>
                ) : invTotal > 0 ? (
                  <>Đang chờ AI xử lý {invTotal} video{aiPending > 0 || aiGenerated > 0 ? ` · ${aiGenerated}/${aiGenerated + aiPending} hoàn tất` : ""}</>
                ) : (
                  <>Chưa có video nào trong Inventory.</>
                )}
              </div>
            ) : null}

            <div>
              <p className="mb-2 text-xs font-semibold text-slate-500 uppercase tracking-wider">Lịch tuần</p>
              <div className="space-y-2">
                {Object.entries(slotsByDay)
                  .sort(([a], [b]) => Number(a) - Number(b))
                  .map(([day, daySlots]) => (
                    <div key={day} className="flex items-center gap-2 rounded-xl border border-slate-100 bg-white p-2">
                      <span className="w-20 shrink-0 text-xs font-bold text-slate-600">
                        {WEEKDAY_NAMES[Number(day)]}
                      </span>
                      <div className="flex flex-wrap gap-1.5">
                        {(daySlots as any[]).map((slot: any) => {
                          const time = slot.time || slot.slot_time || "";
                          return (
                            <span
                              key={time}
                              className="rounded-lg bg-indigo-50 px-2 py-1 text-xs font-semibold text-indigo-700"
                            >
                              {time}
                            </span>
                          );
                        })}
                      </div>
                    </div>
                  ))}
              </div>
            </div>

            <div className="flex items-center gap-3 pt-2 border-t border-slate-100">
              <button
                onClick={() => setEditing(true)}
                className={btnSmall}
                disabled={saving || runningBatch}
              >
                <IconCheck size={14} className="mr-1" />
                Chỉnh sửa
              </button>
              {destinationId && (
                <button
                  onClick={() => setShowRunConfirm(true)}
                  className={btnSmall}
                  disabled={saving || runningBatch}
                >
                  <IconPlay size={14} className="mr-1" />
                  Chạy batch ngay
                </button>
              )}
              {runResult && (
                <span className="text-xs text-slate-600 ml-auto">{runResult}</span>
              )}
            </div>
          </>
        ) : (
          <>
            <div className="space-y-4">
              <div className="flex items-center gap-4">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={scheduleRef.enabled}
                    onChange={(e) => setSchedule(prev => prev ? { ...prev, enabled: e.target.checked } : { ...scheduleRef, enabled: e.target.checked })}
                    className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                  />
                  <span className="text-sm font-medium text-slate-700">Auto Scheduler</span>
                </label>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div>
                  <label className={labelCls}>Timezone</label>
                  <select
                    value={scheduleRef.timezone}
                    onChange={(e) => setSchedule(prev => prev ? { ...prev, timezone: e.target.value } : null)}
                    className={inputCls}
                  >
                    {TIMEZONE_OPTIONS.map(opt => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className={labelCls}>Batch time</label>
                  <input
                    type="time"
                    value={scheduleRef.batch_time}
                    onChange={(e) => setSchedule(prev => prev ? { ...prev, batch_time: e.target.value } : null)}
                    className={inputCls}
                  />
                </div>
                <div>
                  <label className={labelCls}>Max/day</label>
                  <select
                    value={String(scheduleRef.max_daily_publish)}
                    onChange={(e) => setSchedule(prev => prev ? { ...prev, max_daily_publish: Number(e.target.value) } : null)}
                    className={inputCls}
                  >
                    {MAX_DAILY_OPTIONS.map(opt => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div>
                <p className="mb-2 text-xs font-semibold text-slate-500 uppercase tracking-wider">Lịch tuần (tối đa 5 slots/ngày)</p>
                <div className="space-y-2 max-h-96 overflow-y-auto">
                  {WEEKDAY_KEYS.map((dayKey, dayIndex) => (
                    <div key={dayKey} className="flex items-start gap-2 rounded-xl border border-slate-100 bg-white p-2">
                      <span className="w-20 shrink-0 text-xs font-bold text-slate-600 mt-1">
                        {WEEKDAY_NAMES[dayIndex]}
                      </span>
                      <div className="flex-1 flex flex-wrap gap-1.5">
                        {(scheduleRef.slots[dayKey] || []).map((time, index) => (
                          <div key={`${dayKey}-${index}`} className="flex items-center gap-1.5">
                            <input
                              type="time"
                              value={time}
                              onChange={(e) => handleTimeChange(dayKey, index, e.target.value)}
                              className={`${inputCls} w-24`}
                            />
                            <button
                              type="button"
                              onClick={() => handleRemoveSlot(dayKey, index)}
                              className="text-red-500 hover:text-red-700 text-xs p-1"
                              disabled={(scheduleRef.slots[dayKey] || []).length <= 1}
                            >
                              ×
                            </button>
                          </div>
                        ))}
                        {(scheduleRef.slots[dayKey] || []).length < 5 && (
                          <button
                            type="button"
                            onClick={() => handleAddSlot(dayKey)}
                            className="rounded-lg border border-dashed border-slate-300 px-2 py-1 text-xs text-slate-500 hover:bg-slate-50"
                          >
                            + Thêm slot
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="flex items-center gap-3 pt-2 border-t border-slate-100">
              <button
                onClick={handleSave}
                disabled={saving}
                className={`flex items-center gap-1 ${btnSmall}`}
              >
                {saving ? (
                  <>
                    <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" /></svg>
                    Đang lưu...
                  </>
                ) : (
                  <>
                    <IconCheck size={14} />
                    Lưu lịch
                  </>
                )}
              </button>
              <button
                onClick={() => setEditing(false)}
                className={btnSmall}
                disabled={saving}
              >
                Hủy
              </button>
              {runResult && (
                <span className="text-xs text-slate-600 ml-auto">{runResult}</span>
              )}
            </div>
          </>
        )}

        {showRunConfirm && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
            <div className="bg-white rounded-2xl p-6 w-full max-w-md shadow-xl">
              <h3 className="text-lg font-semibold text-slate-900 mb-2">Xác nhận chạy batch ngay</h3>
              <p className="text-sm text-slate-600 mb-4">
                Tính năng này sẽ tạo batch cho hôm nay và upload video lên YouTube (private với publishAt).
                <strong>Video sẽ được đăng thật lên YouTube.</strong>
              </p>
              <div className="flex justify-end gap-3">
                <button
                  onClick={() => setShowRunConfirm(false)}
                  className={btnSmall}
                  disabled={runningBatch}
                >
                  Hủy
                </button>
                <button
                  onClick={handleRunBatch}
                  disabled={runningBatch}
                  className="px-4 py-2 bg-red-600 text-white rounded-lg text-sm font-medium hover:bg-red-700 disabled:opacity-50"
                >
                  {runningBatch ? (
                    <>
                      <svg className="animate-spin h-4 w-4 mr-1" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" /></svg>
                      Đang chạy...
                    </>
                  ) : (
                    "Xác nhận chạy"
                  )}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}