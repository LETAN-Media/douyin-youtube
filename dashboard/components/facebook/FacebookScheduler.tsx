"use client";

import { useState, useCallback, useEffect, useMemo } from "react";
import { Card, CardHeader, Badge, btnSmall, inputCls, labelCls } from "@/components/ui";
import { IconCalendar, IconCheck, IconPlay, IconSparkles, IconX, IconAlert } from "@/components/icons";
import type {
  FacebookScheduleStatus,
  FacebookScheduleDto,
  UpdateFacebookScheduleDto,
  FacebookScheduleGenerationRequest,
  FacebookSchedulePreviewResponse,
} from "@/lib/facebook-api";
import { previewFacebookSchedule, generateAndSaveFacebookSchedule } from "@/lib/facebook-api";

const WEEKDAY_NAMES = ["Chủ nhật", "Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7"];
// Backend (Python) weekday: Monday = 0 … Sunday = 6. WEEKDAY_NAMES above is
// Sunday-first and only matches WEEKDAY_KEYS for the name-keyed edit form.
// Status-driven displays (numeric weekday from the backend) must use this.
const WEEKDAY_NAMES_MONDAY_FIRST = [
  "Thứ 2",
  "Thứ 3",
  "Thứ 4",
  "Thứ 5",
  "Thứ 6",
  "Thứ 7",
  "Chủ nhật",
];
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

const DISTRIBUTION_MODES = [
  { value: "even", label: "Đều trong ngày" },
  { value: "peak_hours", label: "Ưu tiên giờ cao điểm" },
  { value: "channel_stats", label: "Theo thống kê kênh (AI)" },
];

const MAX_SLOTS_PER_DAY = 1000;
const AUTO_SLOT_START = "09:00";
const AUTO_SLOT_END = "22:30";
const MINUTES_PER_DAY = 24 * 60;

function timeToMinutes(value: string): number | null {
  const match = /^([01]\d|2[0-3]):([0-5]\d)$/.exec(value);
  if (!match) return null;
  return Number(match[1]) * 60 + Number(match[2]);
}

function minutesToTime(total: number): string {
  const normalized = ((total % MINUTES_PER_DAY) + MINUTES_PER_DAY) % MINUTES_PER_DAY;
  const hour = Math.floor(normalized / 60);
  const minute = normalized % 60;
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

function distributeSlots(
  maxDaily: number,
  currentTimes: string[],
  fallbackStart: number,
  fallbackEnd: number,
): string[] {
  if (maxDaily <= 0) return [];
  const minutes = currentTimes
    .map(timeToMinutes)
    .filter((value): value is number => value !== null)
    .sort((a, b) => a - b);

  let start = minutes.length >= 2 ? minutes[0] : fallbackStart;
  let end = minutes.length >= 2 ? minutes[minutes.length - 1] : fallbackEnd;
  if (end <= start) {
    start = fallbackStart;
    end = fallbackEnd;
  }
  if (end <= start) return [];

  if (maxDaily === 1) return [minutesToTime(start)];

  const span = end - start;
  if (maxDaily > span + 1) {
    return Array.from({ length: maxDaily }, (_, index) =>
      minutesToTime(Math.floor((index * MINUTES_PER_DAY) / maxDaily)),
    );
  }

  return Array.from({ length: maxDaily }, (_, index) =>
    minutesToTime(Math.round(start + (span * index) / (maxDaily - 1))),
  );
}

function buildAutoSlotMap(
  maxDaily: number,
  currentSlots: Record<string, string[]>,
): Record<string, string[]> {
  const allMinutes = Object.values(currentSlots)
    .flat()
    .map(timeToMinutes)
    .filter((value): value is number => value !== null);

  const fallbackStart =
    allMinutes.length >= 2 ? Math.min(...allMinutes) : timeToMinutes(AUTO_SLOT_START)!;
  const fallbackEnd =
    allMinutes.length >= 2 ? Math.max(...allMinutes) : timeToMinutes(AUTO_SLOT_END)!;

  return Object.fromEntries(
    WEEKDAY_KEYS.map((dayKey) => [
      dayKey,
      distributeSlots(
        maxDaily,
        currentSlots[dayKey] || [],
        fallbackStart,
        fallbackEnd,
      ),
    ]),
  );
}

function parseMaxDailyInput(raw: string): { value: number | null; error: string | null } {
  const text = raw.trim();
  if (!text) return { value: null, error: "Vui lòng nhập Max videos/day." };
  if (!/^\d+$/.test(text)) {
    return { value: null, error: "Max videos/day phải là số nguyên dương." };
  }
  const value = Number(text);
  if (!Number.isSafeInteger(value) || value < 1) {
    return { value: null, error: "Max videos/day phải là số nguyên từ 1 trở lên." };
  }
  if (value > MAX_SLOTS_PER_DAY) {
    return {
      value: null,
      error: `Max videos/day tối đa ${MAX_SLOTS_PER_DAY} (giới hạn an toàn của hệ thống).`,
    };
  }
  return { value, error: null };
}

function schedulerStateLabel(state: FacebookScheduleStatus["scheduler_state"]): string {
  switch (state) {
    case "running":
      return "Running";
    case "daily_limit_reached":
      return "Daily limit reached";
    case "quota_paused":
      return "Quota paused";
    case "no_inventory":
      return "No inventory";
    default:
      return "Waiting";
  }
}

function schedulerStateTone(
  state: FacebookScheduleStatus["scheduler_state"],
): "green" | "amber" | "red" | "slate" {
  switch (state) {
    case "running":
      return "green";
    case "quota_paused":
    case "daily_limit_reached":
      return "amber";
    case "no_inventory":
      return "red";
    default:
      return "slate";
  }
}

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

type BatchRunResult = {
  ok: boolean;
  batch_id: string | null;
  status: string;
  videos_enqueued: number;
  reason: string | null;
  message: string;
  warning?: string | null;
  capacity_limited?: boolean;
  daily_limit?: number | null;
  slot_capacity?: number | null;
};

function describeBatchResult(
  result: BatchRunResult,
  ctx: { inventoryTotal: number | null; aiReady: number | null; dailyLimit: number },
): string {
  const n = result.videos_enqueued ?? 0;
  const reason = result.reason;
  const invSuffix =
    ctx.inventoryTotal !== null && ctx.aiReady !== null
      ? ` · Inventory ${ctx.inventoryTotal} video · ${ctx.aiReady} video AI-ready.`
      : "";
  // A positive enqueue count is always reported as such — never fall back
  // to "no video" wording when videos were actually scheduled.
  if (n > 0 && !reason) {
    return result.warning
      ? `Đã xếp ${n} video vào hàng đợi. ${result.warning}`
      : `Đã xếp ${n} video vào hàng đợi`;
  }
  switch (reason) {
    case "BATCH_ALREADY_COMPLETED":
      return (
        `Batch hôm nay đã chạy xong · ${n} video đã được xếp lịch.` +
        (result.warning ? ` ${result.warning}` : "") +
        invSuffix
      );
    case "BATCH_IN_PROGRESS":
      return "Batch hôm nay đang chạy.";
    case "DAILY_LIMIT_REACHED":
      return `Đã đạt giới hạn phát hành hôm nay (${ctx.dailyLimit} video).`;
    case "QUOTA_PAUSED":
      return "YouTube đang tạm dừng do quota/rate limit. Hệ thống sẽ tự thử lại sau.";
    case "NO_FUTURE_SLOTS":
      return "Hôm nay không còn khung giờ đăng nào ở tương lai.";
    case "AUTO_PUBLISH_DISABLED":
      return "Auto Publish đang tắt — scheduler tự động không chạy (vẫn có thể chạy batch thủ công).";
    case "NO_AI_READY_INVENTORY":
      if (ctx.inventoryTotal !== null && ctx.inventoryTotal > 0) {
        return `Inventory có ${ctx.inventoryTotal} video nhưng hiện có 0 video AI-ready.`;
      }
      return "Chưa có video nào trong Inventory.";
    case "SCHEDULE_NOT_FOUND":
      return "Pipeline chưa cấu hình lịch đăng.";
    case "NOT_BEFORE_BATCH_TIME":
      return "Chưa tới giờ batch hôm nay.";
    case "NO_DESTINATION":
      return "Chưa kết nối kênh YouTube.";
    default:
      if (n > 0) return `Đã xếp ${n} video vào hàng đợi`;
      if (result.message) return result.message;
      return "Không xếp thêm video trong lần bấm này.";
  }
}

async function runBatch(pipelineId: string, destinationId: string): Promise<BatchRunResult> {
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
  const [maxDailyInput, setMaxDailyInput] = useState(
    String(initialSchedule?.max_daily_publish ?? initialStatus?.daily_limit ?? 5),
  );

  // Auto-generate schedule states
  const [showGenerateModal, setShowGenerateModal] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [previewData, setPreviewData] = useState<FacebookSchedulePreviewResponse | null>(null);
  const [genConfig, setGenConfig] = useState<FacebookScheduleGenerationRequest>({
    max_daily_publish: initialSchedule?.max_daily_publish ?? initialStatus?.daily_limit ?? 5,
    start_time: "09:00",
    end_time: "22:00",
    min_interval_minutes: 60,
    weekdays: [0, 1, 2, 3, 4, 5, 6],
    distribution_mode: "even",
    allow_midnight: false,
    separate_weekend: false,
    weekend_start_time: "09:00",
    weekend_end_time: "21:00",
    weekend_min_interval_minutes: 60,
    weekend_max_daily_publish: undefined,
  });

  const scheduleRef = useMemo(
    () =>
      schedule || {
        id: "",
        pipeline_id: pipelineId,
        timezone: "Asia/Ho_Chi_Minh",
        enabled: false, // Default false, will be overridden by user when creating
        max_daily_publish: 5,
        batch_time: "06:00",
        slots: DEFAULT_SLOTS,
        created_at: null,
        updated_at: null,
      },
    [schedule, pipelineId],
  );

  const parsedMaxDaily = parseMaxDailyInput(maxDailyInput);
  const slotLimit = Math.min(
    MAX_SLOTS_PER_DAY,
    Math.max(5, parsedMaxDaily.value ?? scheduleRef.max_daily_publish),
  );

  const refreshStatus = useCallback(async () => {
    try {
      const res = await fetch(
        `/api/facebook/scheduler/${encodeURIComponent(pipelineId)}/status`,
        { cache: "no-store" },
      );
      if (!res.ok) return;
      const data = (await res.json()) as FacebookScheduleStatus | null;
      if (data) setStatus(data);
    } catch {
      // Non-fatal: progress display keeps the last known backend snapshot.
    }
  }, [pipelineId]);

  useEffect(() => {
    const timer = setInterval(refreshStatus, 60000);
    return () => clearInterval(timer);
  }, [refreshStatus]);

  const handleSave = useCallback(async () => {
    // Allow saving even when schedule is null (creating new)
    const toSave = schedule || scheduleRef;
    const parsed = parseMaxDailyInput(maxDailyInput);
    if (parsed.value === null) {
      setRunResult(`Lỗi: ${parsed.error}`);
      setTimeout(() => setRunResult(null), 5000);
      return;
    }
    const slotsToSave =
      parsed.value !== toSave.max_daily_publish
        ? buildAutoSlotMap(parsed.value, toSave.slots)
        : toSave.slots;
    setSaving(true);
    try {
      const payload: UpdateFacebookScheduleDto = {
        enabled: toSave.enabled,
        timezone: toSave.timezone,
        max_daily_publish: parsed.value,
        batch_time: toSave.batch_time,
        slots: slotsToSave,
      };
      const updated = await saveSchedule(pipelineId, payload);
      setSchedule(updated);
      setMaxDailyInput(String(updated.max_daily_publish));
      setEditing(false);
      setRunResult("Đã lưu lịch thành công");
      setTimeout(() => setRunResult(null), 3000);
      void refreshStatus();
    } catch (err: any) {
      setRunResult(`Lỗi: ${err.message || "Không thể lưu lịch"}`);
      setTimeout(() => setRunResult(null), 5000);
    } finally {
      setSaving(false);
    }
  }, [pipelineId, schedule, scheduleRef, maxDailyInput, refreshStatus]);

  const handleRunBatch = useCallback(async () => {
    if (!destinationId) return;
    setRunningBatch(true);
    try {
      const result = await runBatch(pipelineId, destinationId);
      setRunResult(
        describeBatchResult(result, {
          inventoryTotal: status?.inventory_total ?? null,
          aiReady: status?.ai_ready ?? null,
          dailyLimit: schedule?.max_daily_publish ?? status?.daily_limit ?? 5,
        }),
      );
      setTimeout(() => setRunResult(null), result.videos_enqueued > 0 && !result.reason ? 5000 : 8000);
      setShowRunConfirm(false);
      // Refresh counters so the UI reflects any newly queued work.
      void refreshStatus();
    } catch (err: any) {
      setRunResult(`Lỗi: ${err.message || "Không thể chạy batch"}`);
      setTimeout(() => setRunResult(null), 5000);
    } finally {
      setRunningBatch(false);
    }
  }, [pipelineId, destinationId, status, schedule, refreshStatus]);

  // Auto-generate schedule handlers
  const handleOpenGenerateModal = useCallback(() => {
    // Pre-fill config with current schedule values
    setGenConfig(prev => ({
      ...prev,
      max_daily_publish: scheduleRef.max_daily_publish,
    }));
    setPreviewData(null);
    setShowGenerateModal(true);
  }, [scheduleRef]);

  const handleCloseGenerateModal = useCallback(() => {
    setShowGenerateModal(false);
    setPreviewData(null);
  }, []);

  const handleGenConfigChange = useCallback((key: keyof FacebookScheduleGenerationRequest, value: any) => {
    setGenConfig(prev => ({ ...prev, [key]: value }));
  }, []);

  const handlePreviewGenerate = useCallback(async () => {
    setGenerating(true);
    try {
      const preview = await previewFacebookSchedule(pipelineId, genConfig);
      setPreviewData(preview);
    } catch (err: any) {
      setRunResult(`Lỗi xem trước: ${err.message || "Không thể tạo lịch"}`);
      setTimeout(() => setRunResult(null), 5000);
    } finally {
      setGenerating(false);
    }
  }, [pipelineId, genConfig]);

  const handleSaveGenerated = useCallback(async () => {
    if (!previewData?.ok) return;
    setGenerating(true);
    try {
      const generated = await generateAndSaveFacebookSchedule(pipelineId, genConfig);
      setSchedule(generated);
      setMaxDailyInput(String(generated.max_daily_publish));
      setEditing(false);
      setShowGenerateModal(false);
      setPreviewData(null);
      setRunResult("Đã tạo và lưu lịch tự động thành công");
      setTimeout(() => setRunResult(null), 3000);
      void refreshStatus();
    } catch (err: any) {
      setRunResult(`Lỗi lưu lịch: ${err.message || "Không thể lưu lịch"}`);
      setTimeout(() => setRunResult(null), 5000);
    } finally {
      setGenerating(false);
    }
  }, [pipelineId, genConfig, previewData, refreshStatus]);

  const handleMaxDailyChange = (raw: string) => {
    setMaxDailyInput(raw);
    const parsed = parseMaxDailyInput(raw);
    const maxDaily = parsed.value;
    if (maxDaily === null) return;
    setSchedule(prev => {
      const base = prev || scheduleRef;
      return {
        ...base,
        max_daily_publish: maxDaily,
        slots: buildAutoSlotMap(maxDaily, base.slots),
      };
    });
  };

  const handleSlotChange = (dayKey: string, times: string[]) => {
    setSchedule(prev => {
      const base = prev || scheduleRef;
      return { ...base, slots: { ...base.slots, [dayKey]: times } };
    });
  };

  const handleAddSlot = (dayKey: string) => {
    const current = scheduleRef.slots[dayKey] || [];
    if (current.length >= slotLimit) return;
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

  const scheduledToday = status?.scheduled_today ?? 0;
  const dailyLimit = status?.daily_limit ?? scheduleRef.max_daily_publish ?? 5;
  const publishedToday = status?.published_today ?? 0;
  const committedToday = status?.committed_today ?? scheduledToday;
  const remainingToday = status?.remaining_today ?? Math.max(0, dailyLimit - committedToday);
  const schedulerState = status?.scheduler_state ?? "waiting";
  const nextPublishAt = status?.next_publish_at || status?.next_batch_at || null;
  const capacityWarning = status?.capacity_warning ?? null;
  const slots = status?.slots || [];
  const invTotal = status?.inventory_total ?? null;
  const aiReady = status?.ai_ready ?? null;
  const aiGenerated = status?.ai_generated ?? 0;
  const aiPending = status?.ai_pending ?? 0;
  const queueQueued = status?.queue_queued ?? null;
  const queueProcessing = status?.queue_processing ?? null;
  const batchPlanned = status?.batch_planned ?? null;
  const batchUploaded = status?.batch_uploaded ?? null;
  const batchFailed = status?.batch_failed ?? null;
  const batchLastError = status?.batch_last_error ?? null;

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
                Max videos/day: {scheduleRef.max_daily_publish}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-center">
                <p className="text-xs text-slate-500">Scheduler</p>
                <p className="text-sm font-bold text-slate-900">
                  <Badge tone={schedulerStateTone(schedulerState)}>
                    {schedulerStateLabel(schedulerState)}
                  </Badge>
                </p>
              </div>
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-center">
                <p className="text-xs text-slate-500">Đã đăng hôm nay</p>
                <p className="text-sm font-bold text-slate-900">
                  {publishedToday}/{dailyLimit}
                </p>
              </div>
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-center">
                <p className="text-xs text-slate-500">Còn lại</p>
                <p className="text-sm font-bold text-slate-900">
                  {remainingToday}
                </p>
              </div>
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-center">
                <p className="text-xs text-slate-500">Lượt kế tiếp</p>
                <p className="text-sm font-bold text-slate-900">
                  {nextPublishAt
                    ? new Date(nextPublishAt).toLocaleString("vi-VN", {
                        hour: "2-digit",
                        minute: "2-digit",
                        day: "2-digit",
                        month: "2-digit",
                      })
                    : "—"}
                </p>
              </div>
            </div>

            {capacityWarning ? (
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs leading-relaxed text-amber-800">
                {capacityWarning}
              </div>
            ) : null}

            {invTotal !== null || queueQueued !== null || batchPlanned !== null ? (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-center">
                  <p className="text-xs text-slate-500">Inventory</p>
                  <p className="text-sm font-bold text-slate-900">
                    {invTotal ?? "—"}
                  </p>
                </div>
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-center">
                  <p className="text-xs text-slate-500">AI-ready</p>
                  <p className="text-sm font-bold text-slate-900">
                    {aiReady ?? "—"}
                  </p>
                </div>
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-center">
                  <p className="text-xs text-slate-500">Hàng đợi</p>
                  <p className="text-sm font-bold text-slate-900">
                    {queueQueued !== null ? `${queueQueued}${queueProcessing ? ` · ${queueProcessing} đang xử lý` : ""}` : "—"}
                  </p>
                </div>
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-center">
                  <p className="text-xs text-slate-500">Batch (KH/Lên/Xếp lỗi)</p>
                  <p className="text-sm font-bold text-slate-900">
                    {batchPlanned !== null ? `${batchPlanned}/${batchUploaded ?? 0}/${batchFailed ?? 0}` : "—"}
                  </p>
                </div>
              </div>
            ) : null}
            {batchLastError ? (
              <p className="text-xs text-rose-600">Batch lỗi: {batchLastError}</p>
            ) : null}

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
                        {WEEKDAY_NAMES_MONDAY_FIRST[
                          Math.min(Math.max(Number(day), 0), 6)
                        ]}
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
                onClick={() => {
                  setMaxDailyInput(String(scheduleRef.max_daily_publish));
                  setEditing(true);
                }}
                className={btnSmall}
                disabled={saving || runningBatch}
              >
                <IconCheck size={14} className="mr-1" />
                Chỉnh sửa
              </button>
              <button
                onClick={handleOpenGenerateModal}
                className={btnSmall}
                disabled={saving || runningBatch || generating}
              >
                <IconSparkles size={14} className="mr-1" />
                Tự động tạo lịch
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
                  <label className={labelCls}>Max videos/day</label>
                  <input
                    type="number"
                    min={1}
                    max={MAX_SLOTS_PER_DAY}
                    step={1}
                    inputMode="numeric"
                    value={maxDailyInput}
                    onChange={(e) => handleMaxDailyChange(e.target.value)}
                    className={inputCls}
                    aria-invalid={Boolean(parsedMaxDaily.error)}
                  />
                  <p className={`mt-1 text-xs ${parsedMaxDaily.error ? "text-rose-600" : "text-slate-500"}`}>
                    {parsedMaxDaily.error
                      ?? "Số nguyên từ 1 trở lên. Slot sẽ tự động chia đều theo số lượng này trong khung giờ hiện tại."}
                  </p>
                </div>
              </div>

              <div>
                <p className="mb-2 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  Lịch tuần (tối đa {slotLimit} slots/ngày theo Max videos/day)
                </p>
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
                        {(scheduleRef.slots[dayKey] || []).length < slotLimit && (
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
                onClick={() => {
                  setMaxDailyInput(String(scheduleRef.max_daily_publish));
                  setEditing(false);
                }}
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

        {showGenerateModal && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
            <div className="bg-white rounded-2xl p-6 w-full max-w-2xl shadow-xl max-h-[90vh] overflow-y-auto">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-slate-900">
                  <IconSparkles size={18} className="inline mr-2" />
                  Tự động tạo lịch đăng
                </h3>
                <button
                  onClick={handleCloseGenerateModal}
                  className="text-slate-400 hover:text-slate-600 text-xl"
                  disabled={generating}
                >
                  <IconX size={20} />
                </button>
              </div>

              {!previewData ? (
                // Configuration form
                <div className="space-y-4">
                  <p className="text-sm text-slate-600">
                    Cấu hình tham số để hệ thống tự động sinh lịch đăng cho cả tuần.
                    Nhấn <strong>Xem trước</strong> để kiểm tra trước khi lưu.
                  </p>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                      <label className={labelCls}>Max videos/ngày</label>
                      <input
                        type="number"
                        min={1}
                        max={1000}
                        step={1}
                        value={genConfig.max_daily_publish}
                        onChange={(e) => handleGenConfigChange("max_daily_publish", Number(e.target.value))}
                        className={inputCls}
                        disabled={generating}
                      />
                    </div>
                    <div>
                      <label className={labelCls}>Chế độ phân bổ</label>
                      <select
                        value={genConfig.distribution_mode}
                        onChange={(e) => handleGenConfigChange("distribution_mode", e.target.value)}
                        className={inputCls}
                        disabled={generating}
                      >
                        {DISTRIBUTION_MODES.map(opt => (
                          <option key={opt.value} value={opt.value}>{opt.label}</option>
                        ))}
                      </select>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                      <label className={labelCls}>Giờ bắt đầu</label>
                      <input
                        type="time"
                        value={genConfig.start_time}
                        onChange={(e) => handleGenConfigChange("start_time", e.target.value)}
                        className={inputCls}
                        disabled={generating}
                      />
                    </div>
                    <div>
                      <label className={labelCls}>Giờ kết thúc</label>
                      <input
                        type="time"
                        value={genConfig.end_time}
                        onChange={(e) => handleGenConfigChange("end_time", e.target.value)}
                        className={inputCls}
                        disabled={generating}
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                      <label className={labelCls}>Khoảng cách tối thiểu (phút)</label>
                      <input
                        type="number"
                        min={1}
                        max={1440}
                        step={5}
                        value={genConfig.min_interval_minutes}
                        onChange={(e) => handleGenConfigChange("min_interval_minutes", Number(e.target.value))}
                        className={inputCls}
                        disabled={generating}
                      />
                    </div>
                    <div>
                      <label className={labelCls}>Cho phép 00:00–06:00</label>
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={genConfig.allow_midnight}
                          onChange={(e) => handleGenConfigChange("allow_midnight", e.target.checked)}
                          className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                          disabled={generating}
                        />
                        <span className="text-sm text-slate-700">Cho phép đăng trong khung đêm</span>
                      </label>
                    </div>
                  </div>

                  <div className="border-t border-slate-100 pt-4">
                    <label className="flex items-center gap-2 cursor-pointer mb-2">
                      <input
                        type="checkbox"
                        checked={genConfig.separate_weekend}
                        onChange={(e) => handleGenConfigChange("separate_weekend", e.target.checked)}
                        className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                        disabled={generating}
                      />
                      <span className="text-sm font-medium text-slate-700">Cấu hình riêng cho cuối tuần (Thứ 7, CN)</span>
                    </label>
                    {genConfig.separate_weekend && (
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 ml-6">
                        <div>
                          <label className={labelCls}>Giờ bắt đầu (cuối tuần)</label>
                          <input
                            type="time"
                            value={genConfig.weekend_start_time || "09:00"}
                            onChange={(e) => handleGenConfigChange("weekend_start_time", e.target.value)}
                            className={inputCls}
                            disabled={generating}
                          />
                        </div>
                        <div>
                          <label className={labelCls}>Giờ kết thúc (cuối tuần)</label>
                          <input
                            type="time"
                            value={genConfig.weekend_end_time || "21:00"}
                            onChange={(e) => handleGenConfigChange("weekend_end_time", e.target.value)}
                            className={inputCls}
                            disabled={generating}
                          />
                        </div>
                        <div>
                          <label className={labelCls}>Khoảng cách (cuối tuần, phút)</label>
                          <input
                            type="number"
                            min={1}
                            max={1440}
                            step={5}
                            value={genConfig.weekend_min_interval_minutes || 60}
                            onChange={(e) => handleGenConfigChange("weekend_min_interval_minutes", Number(e.target.value))}
                            className={inputCls}
                            disabled={generating}
                          />
                        </div>
                        <div>
                          <label className={labelCls}>Max videos/ngày (cuối tuần)</label>
                          <input
                            type="number"
                            min={1}
                            max={1000}
                            step={1}
                            value={genConfig.weekend_max_daily_publish || ""}
                            onChange={(e) => handleGenConfigChange("weekend_max_daily_publish", e.target.value ? Number(e.target.value) : undefined)}
                            className={inputCls}
                            disabled={generating}
                            placeholder="Mặc định dùng max_daily_publish"
                          />
                        </div>
                      </div>
                    )}
                  </div>

                  <div>
                    <label className={labelCls}>Ngày trong tuần</label>
                    <div className="flex flex-wrap gap-2">
                      {["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"].map((name, idx) => (
                        <label key={idx} className="flex items-center gap-1.5 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={genConfig.weekdays.includes(idx)}
                            onChange={(e) => handleGenConfigChange("weekdays", e.target.checked ? [...genConfig.weekdays, idx] : genConfig.weekdays.filter(d => d !== idx))}
                            className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                            disabled={generating}
                          />
                          <span className="text-xs text-slate-700">{name}</span>
                        </label>
                      ))}
                    </div>
                  </div>

                  <div className="flex gap-3 pt-2">
                    <button
                      onClick={handlePreviewGenerate}
                      disabled={generating}
                      className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 flex items-center gap-2"
                    >
                      {generating ? (
                        <>
                          <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" /></svg>
                          Đang tạo...
                        </>
                      ) : (
                        <>
                          <span className="text-[10px] mr-1">i</span>
                          Xem trước
                        </>
                      )}
                    </button>
                    <button
                      onClick={handleCloseGenerateModal}
                      className={btnSmall}
                      disabled={generating}
                    >
                      Hủy
                    </button>
                  </div>
                </div>
              ) : (
                // Preview result
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <h4 className="text-base font-semibold text-slate-900">Xem trước lịch tuần</h4>
                    <div className="flex gap-2">
                      <button
                        onClick={() => setPreviewData(null)}
                        className={btnSmall}
                        disabled={generating}
                      >
                        Sửa cấu hình
                      </button>
                    </div>
                  </div>

                  {previewData.warnings && previewData.warnings.length > 0 && (
                    <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs leading-relaxed text-amber-800">
                      <p className="font-medium mb-1">Cảnh báo:</p>
                      <ul className="list-disc list-inside space-y-1">
                        {previewData.warnings.map((w, i) => (
                          <li key={i}>{w}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  <div className="space-y-2 max-h-96 overflow-y-auto">
                    {WEEKDAY_KEYS.map((dayKey, dayIndex) => {
                      const daySlots = previewData.slots?.[dayKey] || [];
                      return (
                        <div key={dayKey} className="flex items-start gap-2 rounded-xl border border-slate-100 bg-white p-2">
                          <span className="w-20 shrink-0 text-xs font-bold text-slate-600 mt-1">
                            {WEEKDAY_NAMES[dayIndex]}
                          </span>
                          <div className="flex-1 flex flex-wrap gap-1.5">
                            {daySlots.map((time, tIdx) => (
                              <span
                                key={`${dayKey}-${tIdx}`}
                                className="rounded-lg bg-indigo-50 px-2 py-1 text-xs font-semibold text-indigo-700"
                              >
                                {time}
                              </span>
                            ))}
                            {daySlots.length === 0 && (
                              <span className="text-xs text-slate-400">Không có slot</span>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  {previewData.feasibility_report && (
                    <details className="mt-4 rounded-xl border border-slate-100 bg-slate-50 p-3">
                      <summary className="text-xs font-medium text-slate-600 cursor-pointer">Chi tiết tính khả thi</summary>
                      <pre className="mt-2 text-[10px] text-slate-600 overflow-x-auto">
                        {JSON.stringify(previewData.feasibility_report, null, 2)}
                      </pre>
                    </details>
                  )}

                  <div className="flex justify-end gap-3 pt-4 border-t border-slate-100">
                    <button
                      onClick={() => setPreviewData(null)}
                      className={btnSmall}
                      disabled={generating}
                    >
                      Sửa cấu hình
                    </button>
                    <button
                      onClick={handleSaveGenerated}
                      disabled={generating || !previewData?.ok}
                      className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 flex items-center gap-2"
                    >
                      {generating ? (
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
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}