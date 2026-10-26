"use client";

import type { TikTokFlowBackendStatus, TikTokFlowStep, TikTokFlowActiveEdge } from "@/lib/tiktok-api";
import { Card } from "@/components/ui";
import {
  IconAlert,
  IconCheck,
  IconClock,
  IconDestinations,
  IconInventory,
  IconSparkles,
  IconTikTok,
  IconUpload,
} from "@/components/icons";

const STEP_ICONS: Record<string, (size: number) => React.ReactNode> = {
  source: (s) => (
    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-slate-900 text-white shadow-sm">
      <IconTikTok size={s} />
    </span>
  ),
  inventory: (s) => (
    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600">
      <IconInventory size={s} />
    </span>
  ),
  ai_metadata: (s) => (
    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-violet-50 text-violet-600">
      <IconSparkles size={s} />
    </span>
  ),
  scheduler: (s) => (
    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-amber-50 text-amber-600">
      <IconClock size={s} />
    </span>
  ),
  publisher: (s) => (
    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-sky-50 text-sky-600">
      <IconUpload size={s} />
    </span>
  ),
  youtube_destination: (s) => (
    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-rose-50 text-rose-600">
      <IconDestinations size={s} />
    </span>
  ),
};

const STATUS_META: Record<
  TikTokFlowBackendStatus,
  { label: string; chip: string; dot: string; pulse: boolean; icon: React.ReactNode | null }
> = {
  idle: {
    label: "Idle",
    chip: "bg-slate-100 text-slate-600 ring-slate-200",
    dot: "bg-slate-400",
    pulse: false,
    icon: null,
  },
  ready: {
    label: "Ready",
    chip: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    dot: "bg-emerald-500",
    pulse: false,
    icon: <IconCheck size={11} />,
  },
  waiting: {
    label: "Waiting",
    chip: "bg-amber-50 text-amber-700 ring-amber-200",
    dot: "bg-amber-500",
    pulse: false,
    icon: <IconClock size={11} />,
  },
  running: {
    label: "Running",
    chip: "bg-indigo-50 text-indigo-700 ring-indigo-200",
    dot: "bg-indigo-500",
    pulse: true,
    icon: null,
  },
  partial: {
    label: "Partial",
    chip: "bg-violet-50 text-violet-700 ring-violet-200",
    dot: "bg-violet-500",
    pulse: false,
    icon: <IconSparkles size={11} />,
  },
  done: {
    label: "Done",
    chip: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    dot: "bg-emerald-500",
    pulse: false,
    icon: <IconCheck size={11} />,
  },
  error: {
    label: "Error",
    chip: "bg-rose-50 text-rose-700 ring-rose-200",
    dot: "bg-rose-500",
    pulse: true,
    icon: <IconAlert size={11} />,
  },
  not_configured: {
    label: "Not configured",
    chip: "bg-slate-100 text-slate-500 ring-slate-200",
    dot: "bg-slate-300",
    pulse: false,
    icon: null,
  },
};

export const DEFAULT_TIKTOK_FLOW_STEPS: TikTokFlowStep[] = [
  { key: "source", title: "TikTok Source", subtitle: "Creator profiles", status: "idle" },
  { key: "inventory", title: "Inventory", subtitle: "Video repository", status: "idle" },
  { key: "ai_metadata", title: "AI Metadata", subtitle: "SEO Title & Tags", status: "idle" },
  { key: "scheduler", title: "Scheduler", subtitle: "Automated slots", status: "idle" },
  { key: "publisher", title: "Publisher", subtitle: "Download & Upload", status: "idle" },
  { key: "youtube_destination", title: "YouTube Destination", subtitle: "Target channel", status: "idle" },
];

const EDGE_KEYS: TikTokFlowActiveEdge[] = [
  "source->inventory",
  "inventory->ai_metadata",
  "ai_metadata->scheduler",
  "scheduler->publisher",
  "publisher->youtube_destination",
];

function StepBox({ step }: { step: TikTokFlowStep }) {
  const meta = STATUS_META[step.status] ?? STATUS_META.idle;
  const icon = (STEP_ICONS[step.key] ?? STEP_ICONS.inventory)(17);
  const displayDetail = step.detail ?? step.subtitle;
  const isRunning = step.status === "running";
  const isError = step.status === "error";

  return (
    <div
      className={`flex w-full min-w-0 items-center gap-3 rounded-2xl border bg-white p-3 shadow-sm transition-colors sm:p-3.5 ${
        isRunning
          ? "border-indigo-400 ring-2 ring-indigo-200"
          : isError
            ? "border-rose-400 ring-2 ring-rose-200"
            : step.status === "ready" || step.status === "done"
              ? "border-emerald-200"
              : step.status === "waiting"
                ? "border-amber-200"
                : "border-slate-200/90"
      }`}
    >
      <span className="shrink-0">{icon}</span>
      <div className="min-w-0 flex-1">
        <span className="block truncate text-sm font-extrabold tracking-tight text-slate-900">
          {step.title}
        </span>
        <span className="block truncate text-xs font-medium text-slate-500">
          {displayDetail}
        </span>
      </div>
      <span
        className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-bold ring-1 ring-inset ${meta.chip}`}
      >
        <span className="relative flex h-1.5 w-1.5">
          {meta.pulse ? (
            <span className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 ${meta.dot}`} />
          ) : null}
          <span className={`relative inline-flex h-1.5 w-1.5 rounded-full ${meta.dot}`} />
        </span>
        {meta.icon}
        <span>{meta.label}</span>
      </span>
    </div>
  );
}

function Connector({ isActive }: { isActive: boolean }) {
  return (
    <div className="flex items-center justify-start py-1 pl-7 sm:pl-8">
      <svg
        width="20"
        height="22"
        viewBox="0 0 20 22"
        fill="none"
        aria-hidden="true"
        className="shrink-0"
      >
        <path
          d="M 10 0 L 10 16 M 6 12 L 10 16 L 14 12"
          stroke={isActive ? "#4f46e5" : "#cbd5e1"}
          strokeWidth={isActive ? 2.5 : 1.5}
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeDasharray={isActive ? "3 3" : undefined}
        />
      </svg>
    </div>
  );
}

export function TikTokPipelineFlow({
  steps = DEFAULT_TIKTOK_FLOW_STEPS,
  activeEdges = [],
}: {
  steps?: TikTokFlowStep[];
  activeEdges?: string[];
}) {
  return (
    <div className="w-full min-w-0">
      <div className="flex w-full min-w-0 flex-col items-stretch">
        {steps.map((step, idx) => {
          const edgeKey = EDGE_KEYS[idx];
          const isActive = edgeKey ? activeEdges.includes(edgeKey) : false;
          return (
            <div key={step.key} className="w-full min-w-0">
              <StepBox step={step} />
              {idx < steps.length - 1 ? <Connector isActive={isActive} /> : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function TikTokPipelineFlowCard({
  steps,
  activeEdges,
}: {
  steps?: TikTokFlowStep[];
  activeEdges?: string[];
}) {
  return (
    <Card className="p-0">
      <div className="border-b border-slate-100 px-4 py-3 sm:px-5">
        <p className="text-[11px] font-extrabold uppercase tracking-[0.12em] text-slate-400">
          Sơ đồ TikTok Pipeline Flow
        </p>
      </div>
      <div className="p-4 sm:px-5">
        <TikTokPipelineFlow steps={steps} activeEdges={activeEdges} />
      </div>
    </Card>
  );
}
