"use client";

import type { ReactNode } from "react";

export type FlowNodeTone = "green" | "amber" | "red" | "slate" | "indigo";

const toneChip: Record<FlowNodeTone, string> = {
  green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  amber: "bg-amber-50 text-amber-700 ring-amber-200",
  red: "bg-rose-50 text-rose-700 ring-rose-200",
  slate: "bg-slate-100 text-slate-600 ring-slate-200",
  indigo: "bg-indigo-50 text-indigo-700 ring-indigo-200",
};

const toneDot: Record<FlowNodeTone, string> = {
  green: "bg-emerald-500",
  amber: "bg-amber-500",
  red: "bg-rose-500",
  slate: "bg-slate-400",
  indigo: "bg-indigo-500",
};

export function FlowNode({
  x,
  y,
  width,
  height,
  avatar,
  title,
  subtitle,
  meta,
  statusLabel,
  statusTone,
  statusPulse = false,
  selected = false,
  active = false,
  failed = false,
  dimmed = false,
  badge,
  onClick,
  label,
}: {
  x: number;
  y: number;
  width: number;
  height: number;
  avatar: ReactNode;
  title: string;
  subtitle?: string;
  meta?: ReactNode;
  statusLabel: string;
  statusTone: FlowNodeTone;
  statusPulse?: boolean;
  selected?: boolean;
  active?: boolean;
  failed?: boolean;
  dimmed?: boolean;
  badge?: ReactNode;
  onClick?: () => void;
  label?: string;
}) {
  return (
    <div
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      aria-label={label ?? title}
      onClick={onClick}
      onKeyDown={
        onClick
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onClick();
              }
            }
          : undefined
      }
      className={`absolute flex min-w-0 flex-col justify-center gap-1 rounded-2xl border bg-white p-2 text-left shadow-[0_2px_8px_-2px_rgba(15,23,42,0.12)] transition-all duration-200 ${
        onClick ? "cursor-pointer hover:-translate-y-px hover:border-indigo-300 hover:shadow-md" : ""
      } ${
        selected
          ? "border-indigo-500 ring-2 ring-indigo-300"
          : failed
            ? "border-rose-400 ring-2 ring-rose-200"
            : active
              ? "border-indigo-400 ring-2 ring-indigo-200"
              : "border-slate-200/90"
      } ${dimmed ? "opacity-30 saturate-50" : "opacity-100"}`}
      style={{
        left: x,
        top: y,
        width,
        height,
        ...(active && !selected && !failed
          ? { filter: "drop-shadow(0 0 8px rgba(99,102,241,0.35))" }
          : failed
            ? { filter: "drop-shadow(0 0 8px rgba(244,63,94,0.35))" }
            : undefined),
      }}
    >
      {badge ? <div className="absolute -top-2.5 right-2 z-10">{badge}</div> : null}
      <div className="flex min-w-0 items-center gap-2">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-xl">
          {avatar}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-extrabold leading-tight tracking-tight text-slate-900">
            {title}
          </p>
          {subtitle ? (
            <p className="truncate text-[11px] font-medium leading-tight text-slate-400">{subtitle}</p>
          ) : null}
        </div>
      </div>
      <div className="flex min-w-0 items-center justify-between gap-2">
        {meta ? (
          <div className="tnum min-w-0 flex-1 truncate text-[11px] font-semibold leading-tight text-slate-500">
            {meta}
          </div>
        ) : (
          <span />
        )}
        <span
          className={`inline-flex shrink-0 items-center gap-1 rounded-full px-1.5 py-px text-[10px] font-bold ring-1 ring-inset ${toneChip[statusTone]}`}
        >
          <span className="relative flex h-1.5 w-1.5">
            {statusPulse ? (
              <span className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 ${toneDot[statusTone]}`} />
            ) : null}
            <span className={`relative inline-flex h-1.5 w-1.5 rounded-full ${toneDot[statusTone]}`} />
          </span>
          {statusLabel}
        </span>
      </div>
    </div>
  );
}
