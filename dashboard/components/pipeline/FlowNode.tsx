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
      style={{ left: x, top: y, width, height }}
      className={`absolute flex min-w-0 flex-col justify-center gap-1 rounded-2xl border bg-white p-2.5 text-left shadow-[0_2px_8px_-2px_rgba(15,23,42,0.12)] transition-all duration-200 ${
        onClick ? "cursor-pointer hover:-translate-y-px hover:border-indigo-300 hover:shadow-md" : ""
      } ${selected ? "border-indigo-500 ring-2 ring-indigo-300" : "border-slate-200/90"} ${
        dimmed ? "opacity-35 saturate-50" : "opacity-100"
      }`}
    >
      {badge ? <div className="absolute -top-2.5 right-2">{badge}</div> : null}
      <div className="flex min-w-0 items-center gap-2">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-xl">
          {avatar}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-extrabold leading-tight tracking-tight text-slate-900">
            {title}
          </p>
          {subtitle ? (
            <p className="truncate text-[11px] font-medium text-slate-400">{subtitle}</p>
          ) : null}
        </div>
      </div>
      {meta ? (
        <div className="tnum truncate text-[11px] font-semibold text-slate-500">{meta}</div>
      ) : null}
      <div>
        <span
          className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-bold ring-1 ring-inset ${toneChip[statusTone]}`}
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
