"use client";

import type { FlowRoute } from "@/lib/types";
import { IconAlert, IconCheck, IconClock } from "@/components/icons";

const STAGE_META: Record<string, { label: string; tone: string }> = {
  queued: { label: "Chờ hàng", tone: "bg-slate-100 text-slate-600 ring-slate-200" },
  scheduled: { label: "Đã lên lịch", tone: "bg-sky-50 text-sky-700 ring-sky-200" },
  pending: { label: "Chờ worker", tone: "bg-amber-50 text-amber-700 ring-amber-200" },
  downloading: { label: "Đang tải", tone: "bg-indigo-50 text-indigo-700 ring-indigo-200" },
  uploading: { label: "Đang upload", tone: "bg-indigo-50 text-indigo-700 ring-indigo-200" },
  published: { label: "Hoàn tất", tone: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
  failed: { label: "Thất bại", tone: "bg-rose-50 text-rose-700 ring-rose-200" },
};

export function stageLabel(stage: string): string {
  return STAGE_META[stage]?.label ?? stage;
}

export function formatElapsed(iso?: string | null, nowMs?: number): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  const s = Math.max(0, Math.floor(((nowMs ?? Date.now()) - t) / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}p`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h${m % 60 > 0 ? `${m % 60}p` : ""}`;
  return `${Math.floor(h / 24)}d`;
}

export function ActiveRoutes({
  routes,
  fadingCount,
  selectedKey,
  onSelect,
  nowMs,
}: {
  routes: FlowRoute[];
  fadingCount: number;
  selectedKey: string | null;
  onSelect: (key: string | null) => void;
  nowMs: number;
}) {
  const selected = routes.find((r) => r.key === selectedKey) ?? null;

  return (
    <div className="rounded-2xl border border-slate-200/90 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.05)]">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-3 sm:px-5">
        <h3 className="flex items-center gap-2 text-[11px] font-extrabold uppercase tracking-[0.12em] text-slate-500">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-indigo-400 opacity-60" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-indigo-500" />
          </span>
          Active routes · {routes.filter((r) => !r.failed).length}
          {routes.some((r) => r.failed) ? (
            <span className="text-rose-500">· {routes.filter((r) => r.failed).length} lỗi</span>
          ) : null}
        </h3>
        <p className="text-[11px] font-medium text-slate-400">
          Bấm route để xem chi tiết trace
        </p>
      </div>

      {selected ? (
        <div className="border-b border-slate-100 bg-indigo-50/50 px-4 py-3.5 sm:px-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="truncate text-sm font-extrabold text-slate-900">
                {selected.video_title}
              </p>
              <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500">
                {selected.mode === "manual" ? (
                  <span className="inline-flex items-center rounded-md bg-amber-50 px-1.5 py-0.5 text-[9px] font-black uppercase tracking-wider text-amber-700 ring-1 ring-inset ring-amber-300">
                    MANUAL
                  </span>
                ) : null}
                <span className="font-bold text-slate-700">{selected.source_name}</span>
                <span aria-hidden>→</span>
                <StageChip stage={selected.failed ? "failed" : selected.stage} />
                <span aria-hidden>→</span>
                <span className="font-bold text-slate-700">{selected.destination_name}</span>
              </p>
              <dl className="mt-2.5 grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs sm:grid-cols-4">
                <div>
                  <dt className="font-semibold text-slate-400">Tiến độ</dt>
                  <dd className="tnum mt-0.5 font-extrabold text-slate-900">
                    {selected.progress != null ? `${selected.progress}%` : stageLabel(selected.failed ? "failed" : selected.stage)}
                  </dd>
                </div>
                <div>
                  <dt className="font-semibold text-slate-400">Bắt đầu</dt>
                  <dd className="tnum mt-0.5 font-bold text-slate-700">
                    {formatElapsed(selected.started_at, nowMs)} trước
                  </dd>
                </div>
                <div>
                  <dt className="font-semibold text-slate-400">Attempts</dt>
                  <dd className="tnum mt-0.5 font-bold text-slate-700">{selected.attempts}</dd>
                </div>
                <div>
                  <dt className="font-semibold text-slate-400">Stage</dt>
                  <dd className="mt-0.5 font-mono text-[11px] font-bold text-slate-700">{selected.stage}</dd>
                </div>
              </dl>
              {selected.progress != null ? (
                <div className="mt-2 h-1.5 w-full max-w-xs overflow-hidden rounded-full bg-slate-200/70">
                  <div
                    className={`h-full rounded-full ${selected.failed ? "bg-rose-500" : "bg-gradient-to-r from-violet-500 via-blue-500 to-cyan-400"}`}
                    style={{ width: `${Math.max(2, Math.min(100, selected.progress))}%` }}
                  />
                </div>
              ) : null}
              {selected.failed && selected.error ? (
                <p className="mt-2 flex items-start gap-1.5 break-words rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs font-medium text-rose-700">
                  <IconAlert size={14} />
                  {selected.error.slice(0, 400)}
                </p>
              ) : null}
            </div>
            <button
              type="button"
              onClick={() => onSelect(null)}
              className="inline-flex min-h-[32px] items-center rounded-lg px-2.5 py-1 text-xs font-bold text-slate-500 transition hover:bg-slate-200/70 hover:text-slate-800"
            >
              Đóng
            </button>
          </div>
        </div>
      ) : null}

      {routes.length === 0 ? (
        <div className="flex items-center gap-3 px-4 py-5 sm:px-5">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-slate-100 text-slate-400">
            <IconCheck size={16} />
          </span>
          <div>
            <p className="text-sm font-bold text-slate-700">Không có route nào đang chạy</p>
            <p className="text-xs text-slate-500">
              Toàn bộ connectors xám / idle. Route mới sẽ sáng lên tự động.
            </p>
          </div>
        </div>
      ) : (
        <ul className="divide-y divide-slate-100">
          {routes.map((r) => {
            const active = r.key === selectedKey;
            const meta = STAGE_META[r.failed ? "failed" : r.stage] ?? STAGE_META.queued;
            return (
              <li key={r.key}>
                <button
                  type="button"
                  onClick={() => onSelect(active ? null : r.key)}
                  className={`flex w-full min-h-[52px] flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-left transition sm:px-5 ${
                    active ? "bg-indigo-50/70" : "hover:bg-slate-50"
                  }`}
                >
                  <span className={`h-2 w-2 shrink-0 rounded-full ${r.failed ? "bg-rose-500" : "bg-gradient-to-br from-violet-500 to-cyan-400"}`} />
                  <span className="min-w-0 flex-1 truncate text-[13px]">
                    {r.mode === "manual" ? (
                      <span className="mr-1.5 inline-flex items-center rounded bg-amber-50 px-1.5 py-0.5 text-[9px] font-black uppercase tracking-wider text-amber-700 ring-1 ring-inset ring-amber-300">
                        MANUAL
                      </span>
                    ) : null}
                    <span className="font-bold text-slate-800">{r.source_name}</span>
                    <span className="mx-1.5 text-slate-300">→</span>
                    <span className="font-medium text-slate-500">{r.destination_name}</span>
                    <span className="mx-1.5 hidden truncate font-normal text-slate-400 sm:inline">
                      · {r.video_title}
                    </span>
                  </span>
                  {r.progress != null && !r.failed ? (
                    <span className="tnum text-xs font-extrabold text-indigo-600">{r.progress}%</span>
                  ) : null}
                  <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold ring-1 ring-inset ${meta.tone}`}>
                    {r.failed ? <IconAlert size={11} /> : null}
                    {meta.label}
                  </span>
                  <span className="tnum flex items-center gap-1 text-[11px] font-medium text-slate-400">
                    <IconClock size={12} />
                    {formatElapsed(r.started_at, nowMs)}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {fadingCount > 0 ? (
        <p className="border-t border-slate-100 px-4 py-2 text-[11px] font-medium text-emerald-600 sm:px-5">
          {fadingCount} route vừa hoàn tất — glow đang mờ dần.
        </p>
      ) : null}
    </div>
  );
}

export function StageChip({ stage }: { stage: string }) {
  const meta = STAGE_META[stage] ?? STAGE_META.queued;
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold ring-1 ring-inset ${meta.tone}`}>
      {meta.label}
    </span>
  );
}
