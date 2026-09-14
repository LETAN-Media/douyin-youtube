import type { ReactNode } from "react";

// ---------- Badges ----------

const toneClasses: Record<string, string> = {
  green: "bg-emerald-100 text-emerald-800 ring-emerald-200",
  amber: "bg-amber-100 text-amber-800 ring-amber-200",
  red: "bg-red-100 text-red-800 ring-red-200",
  blue: "bg-blue-100 text-blue-800 ring-blue-200",
  slate: "bg-slate-100 text-slate-700 ring-slate-200",
  indigo: "bg-indigo-100 text-indigo-800 ring-indigo-200",
};

export function Badge({
  tone = "slate",
  children,
}: {
  tone?: keyof typeof toneClasses | string;
  children: ReactNode;
}) {
  const cls = toneClasses[tone] ?? toneClasses.slate;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset ${cls}`}
    >
      {children}
    </span>
  );
}

// ---------- Cards / layout ----------

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-2xl border border-slate-200 bg-white shadow-sm ${className}`}
    >
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-4 py-3 sm:px-5">
      <div className="min-w-0">
        <h2 className="truncate text-sm font-semibold text-slate-900">{title}</h2>
        {subtitle ? (
          <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>
        ) : null}
      </div>
      {action}
    </div>
  );
}

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-10 text-center">
      <div className="flex h-11 w-11 items-center justify-center rounded-full bg-slate-100 text-lg text-slate-400">
        ◌
      </div>
      <p className="text-sm font-semibold text-slate-700">{title}</p>
      {hint ? <p className="max-w-sm text-xs text-slate-500">{hint}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

// ---------- Skeleton ----------

export function SkeletonCard() {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="skeleton-bar h-4 w-2/3 rounded" />
      <div className="skeleton-bar mt-3 h-3 w-full rounded" />
      <div className="skeleton-bar mt-2 h-3 w-5/6 rounded" />
      <div className="mt-4 grid grid-cols-3 gap-2">
        <div className="skeleton-bar h-10 rounded-lg" />
        <div className="skeleton-bar h-10 rounded-lg" />
        <div className="skeleton-bar h-10 rounded-lg" />
      </div>
    </div>
  );
}

export function SkeletonList({ rows = 5 }: { rows?: number }) {
  return (
    <div className="divide-y divide-slate-100">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-3 px-4 py-3 sm:px-5">
          <div className="skeleton-bar h-9 w-9 shrink-0 rounded-lg" />
          <div className="min-w-0 flex-1">
            <div className="skeleton-bar h-3.5 w-1/2 rounded" />
            <div className="skeleton-bar mt-2 h-3 w-1/3 rounded" />
          </div>
          <div className="skeleton-bar h-6 w-16 shrink-0 rounded-full" />
        </div>
      ))}
    </div>
  );
}

// ---------- Buttons / inputs (shared classnames) ----------

export const btnPrimary =
  "inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-xl bg-indigo-600 px-3.5 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50";
export const btnSecondary =
  "inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-sm font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50";
export const btnDanger =
  "inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-xl bg-red-600 px-3.5 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-red-500 disabled:cursor-not-allowed disabled:opacity-50";
export const btnDangerGhost =
  "inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-xl border border-red-200 bg-white px-3 py-1.5 text-xs font-semibold text-red-700 transition hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50 sm:min-h-[32px]";
export const btnSmall =
  "inline-flex min-h-[44px] items-center justify-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 sm:min-h-[32px]";
export const inputCls =
  "w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm outline-none transition placeholder:text-slate-400 focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100";
export const labelCls =
  "mb-1 block text-xs font-semibold text-slate-600";
