"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge, btnPrimary, btnSecondary, labelCls } from "@/components/ui";
import {
  actionGetRescheduleOptions,
  actionReschedulePublication,
} from "@/lib/actions";
import { formatDateTime, publicationLabel } from "@/lib/format";
import type { Publication, RescheduleOptions } from "@/lib/types";
import {
  formatScheduleLabel,
  localDateTimeToUtcIso,
  todayInZone,
  utcIsoToLocalInput,
} from "@/lib/timezone";

// 16px on mobile: Safari iOS zooms the page on smaller inputs and then hides
// the sticky action bar behind the keyboard.
const fieldCls =
  "w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-base text-slate-900 shadow-sm outline-none transition placeholder:text-slate-400 hover:border-slate-300 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100 sm:text-sm";

function previewIso(
  date: string,
  time: string,
  timeZone: string,
): { iso: string | null; error: string | null } {
  if (!date || !time) return { iso: null, error: null };
  try {
    return { iso: localDateTimeToUtcIso(date, time, timeZone), error: null };
  } catch (e) {
    return {
      iso: null,
      error: e instanceof Error ? e.message : "Ngày hoặc giờ không hợp lệ.",
    };
  }
}

export function RescheduleDialog({
  pipelineId,
  publication,
  destinationName,
  onClose,
  onDone,
}: {
  pipelineId: string;
  publication: Publication;
  destinationName: string;
  onClose: () => void;
  onDone: (message: string) => void;
}) {
  const [options, setOptions] = useState<RescheduleOptions | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [date, setDate] = useState("");
  const [time, setTime] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    void actionGetRescheduleOptions(publication.id).then((result) => {
      if (cancelled) return;
      if (!result.ok) {
        setLoadError(result.error);
        setLoading(false);
        return;
      }
      const opts = result.options;
      setOptions(opts);
      // Future schedule -> edit the real time. Past/missing -> the next valid
      // slot proposed by the destination configuration.
      const anchor =
        opts.current_is_future && opts.scheduled_at
          ? opts.scheduled_at
          : opts.suggested_at;
      const local = utcIsoToLocalInput(anchor, opts.timezone);
      setDate(local.date);
      setTime(local.time);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [publication.id]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = previousOverflow;
    };
  }, [onClose]);

  const tz = options?.timezone ?? "UTC";
  const preview = useMemo(() => previewIso(date, time, tz), [date, time, tz]);
  const isPast = useMemo(() => {
    if (!preview.iso) return false;
    return new Date(preview.iso).getTime() <= Date.now();
  }, [preview.iso]);

  const label = publicationLabel(publication.status);
  const blocked = options !== null && !options.can_reschedule;

  const submit = useCallback(async () => {
    if (!options || saving) return;
    setError(null);
    if (!preview.iso) {
      setError(preview.error ?? "Chọn ngày và giờ mới.");
      return;
    }
    setSaving(true);
    const result = await actionReschedulePublication(
      pipelineId,
      publication.id,
      preview.iso,
    );
    setSaving(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    onDone(`Đã đổi lịch sang ${formatScheduleLabel(preview.iso, options.timezone)}.`);
  }, [
    onDone,
    options,
    pipelineId,
    preview.error,
    preview.iso,
    publication.id,
    saving,
  ]);

  const applySlot = (value: string | null) => {
    if (!value) return;
    const local = utcIsoToLocalInput(value, tz);
    setDate(local.date);
    setTime(local.time);
    setError(null);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/50 backdrop-blur-sm sm:items-center sm:p-4"
      role="presentation"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="reschedule-title"
        className="flex max-h-[92dvh] w-full flex-col overflow-hidden rounded-t-2xl bg-white shadow-2xl sm:max-w-lg sm:rounded-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-3 border-b border-slate-100 px-4 py-3.5">
          <div className="min-w-0">
            <h2
              id="reschedule-title"
              className="text-base font-extrabold text-slate-900"
            >
              Đổi lịch publication
            </h2>
            <p className="mt-0.5 text-xs text-slate-500">
              Chọn ngày và giờ mới. Hệ thống kiểm tra slot, Daily Upload Limit và
              khoảng cách tối thiểu giữa hai lần đăng.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Đóng"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-xl leading-none text-slate-500 transition hover:bg-slate-100"
          >
            ×
          </button>
        </header>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
          <dl className="grid gap-2.5 rounded-xl bg-slate-50 p-3 text-xs sm:grid-cols-2">
            <div className="min-w-0">
              <dt className="font-bold uppercase tracking-[0.08em] text-slate-500">
                Video
              </dt>
              <dd className="mt-0.5 break-words text-sm font-semibold text-slate-900">
                {publication.title ||
                  options?.video_title ||
                  `Publication ${publication.id.slice(0, 8)}`}
              </dd>
            </div>
            <div className="min-w-0">
              <dt className="font-bold uppercase tracking-[0.08em] text-slate-500">
                Kênh YouTube đích
              </dt>
              <dd className="mt-0.5 break-words text-sm font-semibold text-slate-900">
                {destinationName}
              </dd>
            </div>
            <div>
              <dt className="font-bold uppercase tracking-[0.08em] text-slate-500">
                Trạng thái hiện tại
              </dt>
              <dd className="mt-1">
                <Badge tone={label.tone}>{label.text}</Badge>
              </dd>
            </div>
            <div className="min-w-0">
              <dt className="font-bold uppercase tracking-[0.08em] text-slate-500">
                Đã lên lịch
              </dt>
              <dd className="mt-0.5 text-sm font-semibold text-slate-900">
                {options?.scheduled_at_label ??
                  formatDateTime(publication.scheduled_at)}
              </dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="font-bold uppercase tracking-[0.08em] text-slate-500">
                Múi giờ áp dụng
              </dt>
              <dd className="mt-0.5 text-sm font-semibold text-slate-900">
                {options?.timezone_label ?? "UTC"}
              </dd>
            </div>
          </dl>

          {loading ? (
            <p className="text-sm text-slate-500">Đang tải thông tin lịch…</p>
          ) : null}
          {loadError ? (
            <p role="alert" className="rounded-xl bg-rose-50 p-3 text-sm text-rose-700">
              {loadError}
            </p>
          ) : null}
          {blocked && options?.block_reason ? (
            <p role="alert" className="rounded-xl bg-amber-50 p-3 text-sm text-amber-800">
              {options.block_reason}
            </p>
          ) : null}

          {options ? (
            <>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <label className={labelCls} htmlFor="reschedule-date">
                  Ngày mới
                  <input
                    id="reschedule-date"
                    type="date"
                    value={date}
                    min={todayInZone(options.timezone)}
                    onChange={(event) => {
                      setDate(event.target.value);
                      setError(null);
                    }}
                    className={`${fieldCls} mt-1`}
                  />
                </label>
                <label className={labelCls} htmlFor="reschedule-time">
                  Giờ mới
                  <input
                    id="reschedule-time"
                    type="time"
                    value={time}
                    step={300}
                    onChange={(event) => {
                      setTime(event.target.value);
                      setError(null);
                    }}
                    className={`${fieldCls} mt-1`}
                  />
                </label>
              </div>

              <div className="space-y-1.5">
                <p className="text-xs text-slate-500">
                  Gợi ý theo cấu hình kênh ({options.timezone_label}). Chạm để dùng.
                </p>
                <div className="flex flex-wrap gap-1.5">
                  <button
                    type="button"
                    onClick={() => applySlot(options.suggested_at)}
                    className="rounded-lg border border-indigo-200 bg-indigo-50 px-2.5 py-1.5 text-xs font-semibold text-indigo-700 transition hover:bg-indigo-100"
                  >
                    Giờ trống tiếp theo · {options.suggested_at_label}
                  </button>
                  {options.next_free_slots
                    .filter((slot) => slot.at !== options.suggested_at)
                    .slice(0, 2)
                    .map((slot) => (
                      <button
                        key={slot.at}
                        type="button"
                        onClick={() => applySlot(slot.at)}
                        className="rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-600 transition hover:bg-slate-50"
                      >
                        {slot.label}
                      </button>
                    ))}
                </div>
              </div>

              <div className="rounded-xl border border-indigo-100 bg-indigo-50/60 px-3 py-2.5">
                <p className="text-sm font-bold text-indigo-900">
                  Lịch mới:{" "}
                  {preview.iso
                    ? formatScheduleLabel(preview.iso, options.timezone)
                    : "—"}
                </p>
                <p className="mt-0.5 break-all text-[11px] text-indigo-700">
                  Gửi API (UTC ISO 8601): {preview.iso ?? "—"}
                </p>
                <p className="mt-1 text-[11px] text-indigo-700">
                  Daily limit: {options.used_on_target_day}/{options.daily_limit}{" "}
                  lượt · tối thiểu {options.minimum_interval_minutes} phút giữa hai
                  lần đăng
                  {options.youtube_native
                    ? " · video đã lên lịch trực tiếp trên YouTube"
                    : ""}
                </p>
              </div>

              {preview.error ? (
                <p role="alert" className="text-sm text-rose-700">
                  {preview.error}
                </p>
              ) : null}
              {isPast ? (
                <p role="alert" className="text-sm text-rose-700">
                  Thời điểm mới phải ở tương lai.
                </p>
              ) : null}
              {error ? (
                <p
                  role="alert"
                  className="rounded-xl bg-rose-50 p-3 text-sm text-rose-700"
                >
                  {error}
                </p>
              ) : null}
            </>
          ) : null}
        </div>

        <footer className="flex flex-col-reverse gap-2 border-t border-slate-100 bg-white px-4 pt-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] sm:flex-row sm:justify-end">
          <button
            type="button"
            className={`${btnSecondary} w-full sm:w-auto`}
            onClick={onClose}
            disabled={saving}
          >
            Hủy
          </button>
          <button
            type="button"
            className={`${btnPrimary} w-full sm:w-auto`}
            onClick={() => void submit()}
            disabled={
              saving || loading || blocked || isPast || !preview.iso || !!loadError
            }
          >
            {saving ? "Đang lưu…" : "Xác nhận đổi lịch"}
          </button>
        </footer>
      </div>
    </div>
  );
}
