"use client";

import { useMemo } from "react";
import type { YouTubePublishMode } from "@/lib/types";

interface Props {
  mode: YouTubePublishMode;
  onModeChange: (m: YouTubePublishMode) => void;
  date: string;
  time: string;
  timezone: string;
  onDateChange: (v: string) => void;
  onTimeChange: (v: string) => void;
  onTimezoneChange: (v: string) => void;
}

const TIMEZONES = ["Asia/Ho_Chi_Minh", "Asia/Bangkok", "Asia/Singapore", "UTC"];

export function YouTubePublishSelector({
  mode,
  onModeChange,
  date,
  time,
  timezone,
  onDateChange,
  onTimeChange,
  onTimezoneChange,
}: Props) {
  const preview = useMemo(() => {
    if (mode !== "scheduled" || !date || !time) return null;
    try {
      // Preview in local terms (backend canonicalizes to UTC).
      const d = new Date(`${date}T${time}:00`);
      if (Number.isNaN(d.getTime())) return null;
      return `Scheduled: ${date} ${time} ${timezone}`;
    } catch {
      return null;
    }
  }, [mode, date, time, timezone]);

  const options: { value: YouTubePublishMode; label: string; hint: string }[] = [
    { value: "immediate", label: "Publish immediately", hint: "Public ngay" },
    { value: "scheduled", label: "Schedule", hint: "Private + publishAt" },
    { value: "private", label: "Private", hint: "Chỉ mình bạn" },
    { value: "unlisted", label: "Unlisted", hint: "Ai có link xem" },
  ];

  return (
    <div className="w-full max-w-full overflow-hidden rounded-2xl border border-slate-200 bg-white p-4">
      <p className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
        YouTube publishing
      </p>
      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
        {options.map((o) => {
          const active = mode === o.value;
          return (
            <button
              key={o.value}
              type="button"
              onClick={() => onModeChange(o.value)}
              className={`flex min-h-[48px] items-center gap-2.5 rounded-xl border px-3 py-2 text-left transition ${
                active
                  ? "border-indigo-500 bg-indigo-50/60 ring-2 ring-indigo-500/20"
                  : "border-slate-200 bg-white hover:border-slate-300"
              }`}
            >
              <span
                className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border-2 ${
                  active ? "border-indigo-600" : "border-slate-300"
                }`}
              >
                {active ? <span className="h-2 w-2 rounded-full bg-indigo-600" /> : null}
              </span>
              <span className="min-w-0">
                <span className="block truncate text-sm font-bold text-slate-900">
                  {o.label}
                </span>
                <span className="block truncate text-[11px] text-slate-500">{o.hint}</span>
              </span>
            </button>
          );
        })}
      </div>

      {mode === "scheduled" ? (
        <div className="mt-3 space-y-2.5 rounded-xl bg-slate-50 p-3">
          <div className="grid grid-cols-1 gap-2.5">
            <label className="block">
              <span className="text-[11px] font-bold text-slate-600">Date (26/09/2026)</span>
              <input
                type="date"
                value={date}
                onChange={(e) => onDateChange(e.target.value)}
                className="mt-1 w-full min-w-0 rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900"
              />
            </label>
            <div className="grid grid-cols-2 gap-2.5">
              <label className="block min-w-0">
                <span className="text-[11px] font-bold text-slate-600">Time (19:30)</span>
                <input
                  type="time"
                  value={time}
                  onChange={(e) => onTimeChange(e.target.value)}
                  className="mt-1 w-full min-w-0 rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900"
                />
              </label>
              <label className="block min-w-0">
                <span className="text-[11px] font-bold text-slate-600">Timezone</span>
                <select
                  value={timezone}
                  onChange={(e) => onTimezoneChange(e.target.value)}
                  className="mt-1 w-full min-w-0 rounded-xl border border-slate-200 bg-white px-2 py-2.5 text-xs text-slate-900"
                >
                  {TIMEZONES.map((tz) => (
                    <option key={tz} value={tz}>
                      {tz}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>
          {preview ? (
            <p className="truncate rounded-lg bg-indigo-50 px-2.5 py-1.5 text-[11px] font-semibold text-indigo-700">
              {preview}
            </p>
          ) : (
            <p className="text-[11px] text-slate-500">
              Chọn ngày giờ tương lai (tối thiểu +5 phút). Video sẽ upload ngay ở
              chế độ private, YouTube tự public đúng giờ.
            </p>
          )}
        </div>
      ) : null}
    </div>
  );
}
