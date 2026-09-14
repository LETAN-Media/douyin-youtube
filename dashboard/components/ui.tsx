import type { ReactNode } from "react";

// ---------- Badges ----------

const toneClasses: Record<string, string> = {
  green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  amber: "bg-amber-50 text-amber-700 ring-amber-200",
  red: "bg-rose-50 text-rose-700 ring-rose-200",
  blue: "bg-sky-50 text-sky-700 ring-sky-200",
  slate: "bg-slate-100 text-slate-600 ring-slate-200",
  indigo: "bg-indigo-50 text-indigo-700 ring-indigo-200",
};

const dotClasses: Record<string, string> = {
  green: "bg-emerald-500",
  amber: "bg-amber-500",
  red: "bg-rose-500",
  blue: "bg-sky-500",
  slate: "bg-slate-400",
  indigo: "bg-indigo-500",
};

export function Badge({
  tone = "slate",
  dot = false,
  children,
}: {
  tone?: keyof typeof toneClasses | string;
  dot?: boolean;
  children: ReactNode;
}) {
  const cls = toneClasses[tone] ?? toneClasses.slate;
  const dc = dotClasses[tone] ?? dotClasses.slate;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1 ring-inset ${cls}`}
    >
      {dot ? <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${dc}`} /> : null}
      {children}
    </span>
  );
}

// ---------- Spinner ----------

export function Spinner({ size = 14 }: { size?: number }) {
  return (
    <span
      aria-hidden
      style={{ width: size, height: size }}
      className="inline-block animate-spin rounded-full border-2 border-current border-t-transparent opacity-70"
    />
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
      className={`rounded-2xl border border-slate-200/90 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.05)] ${className}`}
    >
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  subtitle,
  action,
  icon,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-4 py-3.5 sm:px-5">
      <div className="flex min-w-0 items-center gap-2.5">
        {icon ? (
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600">
            {icon}
          </span>
        ) : null}
        <div className="min-w-0">
          <h2 className="truncate text-sm font-bold text-slate-900">{title}</h2>
          {subtitle ? (
            <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>
          ) : null}
        </div>
      </div>
      {action}
    </div>
  );
}

export function EmptyState({
  title,
  hint,
  action,
  icon,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-12 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-100 text-lg text-slate-400">
        {icon ?? "◌"}
      </div>
      <p className="text-sm font-bold text-slate-800">{title}</p>
      {hint ? <p className="max-w-sm text-xs leading-relaxed text-slate-500">{hint}</p> : null}
      {action ? <div className="mt-3">{action}</div> : null}
    </div>
  );
}

// ---------- Page header ----------

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        {eyebrow ? (
          <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-indigo-600">
            {eyebrow}
          </p>
        ) : null}
        <h1 className="mt-0.5 truncate text-xl font-extrabold tracking-tight text-slate-900 sm:text-2xl">
          {title}
        </h1>
        {description ? (
          <p className="mt-1 text-sm text-slate-500">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

// ---------- Stat card ----------

export function StatCard({
  label,
  value,
  sub,
  icon,
  accent = "indigo",
  alert = false,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  icon?: ReactNode;
  accent?: "indigo" | "emerald" | "amber" | "rose" | "sky" | "slate";
  alert?: boolean;
}) {
  const accents: Record<string, string> = {
    indigo: "bg-indigo-50 text-indigo-600",
    emerald: "bg-emerald-50 text-emerald-600",
    amber: "bg-amber-50 text-amber-600",
    rose: "bg-rose-50 text-rose-600",
    sky: "bg-sky-50 text-sky-600",
    slate: "bg-slate-100 text-slate-500",
  };
  return (
    <div
      className={`rounded-2xl border bg-white p-4 shadow-[0_1px_2px_rgba(15,23,42,0.05)] ${
        alert ? "border-rose-200" : "border-slate-200/90"
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <p className="text-[11px] font-bold uppercase tracking-[0.08em] text-slate-500">
          {label}
        </p>
        {icon ? (
          <span
            className={`flex h-7 w-7 items-center justify-center rounded-lg ${accents[accent]}`}
          >
            {icon}
          </span>
        ) : null}
      </div>
      <p className={`tnum mt-1.5 text-[26px] font-extrabold leading-none tracking-tight ${alert ? "text-rose-600" : "text-slate-900"}`}>
        {value}
      </p>
      {sub ? <p className="mt-1.5 text-xs text-slate-500">{sub}</p> : null}
    </div>
  );
}

// ---------- Progress ----------

export function ProgressBar({
  value,
  max = 100,
  tone = "indigo",
}: {
  value: number;
  max?: number;
  tone?: "indigo" | "emerald" | "amber" | "rose";
}) {
  const pct = Math.max(0, Math.min(100, max > 0 ? (value / max) * 100 : 0));
  const tones: Record<string, string> = {
    indigo: "bg-indigo-500",
    emerald: "bg-emerald-500",
    amber: "bg-amber-500",
    rose: "bg-rose-500",
  };
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
      <div
        className={`h-full rounded-full transition-all ${tones[tone]}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

// ---------- Back link ----------

export const backLinkCls =
  "inline-flex min-h-[44px] items-center gap-1.5 rounded-lg px-2 py-1 text-sm font-semibold text-indigo-600 transition hover:bg-indigo-50 hover:text-indigo-700 sm:min-h-[32px]";

// ---------- Skeleton ----------

export function SkeletonCard() {
  return (
    <div className="rounded-2xl border border-slate-200/90 bg-white p-5 shadow-sm">
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
  "inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-[0_1px_2px_rgba(79,70,229,0.4)] transition hover:bg-indigo-500 active:bg-indigo-600 disabled:cursor-not-allowed disabled:opacity-50 sm:min-h-[38px]";
export const btnSecondary =
  "inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 shadow-sm transition hover:border-slate-300 hover:bg-slate-50 active:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50 sm:min-h-[38px]";
export const btnDanger =
  "inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-xl bg-rose-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-rose-500 disabled:cursor-not-allowed disabled:opacity-50 sm:min-h-[38px]";
export const btnDangerGhost =
  "inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-xl border border-rose-200 bg-white px-3 py-1.5 text-xs font-semibold text-rose-700 transition hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-50 sm:min-h-[32px]";
export const btnSmall =
  "inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm transition hover:border-slate-300 hover:bg-slate-50 active:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50 sm:min-h-[32px]";
export const btnGhost =
  "inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold text-slate-600 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50 sm:min-h-[32px]";
export const inputCls =
  "w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-900 shadow-sm outline-none transition placeholder:text-slate-400 hover:border-slate-300 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100";
export const labelCls =
  "mb-1.5 block text-xs font-bold text-slate-600";
