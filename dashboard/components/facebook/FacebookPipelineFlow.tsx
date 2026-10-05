"use client";

import { useId } from "react";
import type { FacebookFlowBackendStatus, FacebookFlowActiveEdge } from "@/lib/facebook-api";
import { Card } from "@/components/ui";
import {
  IconAlert,
  IconCheck,
  IconClock,
  IconDestinations,
  IconFacebook,
  IconInventory,
  IconSparkles,
  IconUpload,
} from "@/components/icons";
import { FlowEdge, type FlowEdgeLook } from "@/components/pipeline/FlowConnector";
import { vPath } from "@/lib/flowLayout";

// Visual states for UI (subset of backend statuses + internal)
// These map 1:1 with backend statuses where possible
export type FacebookFlowVisualStatus = FacebookFlowBackendStatus;

export type FacebookFlowStep = {
  key: string;
  title: string;
  subtitle: string;
  status: FacebookFlowBackendStatus;
  detail?: string;
};

/** Backend -> visual mapping (single place). Keeps backend semantics. */
export function normalizeFlowStatus(s: FacebookFlowBackendStatus): FacebookFlowVisualStatus {
  // Direct 1:1 mapping - all backend statuses are valid visual states
  return s;
}

const STEP_ICONS: Record<string, (size: number) => React.ReactNode> = {
  source: (s) => (
    <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-sky-500 to-blue-600 text-white">
      <IconFacebook size={s} />
    </span>
  ),
  inventory: (s) => (
    <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-100 text-indigo-600">
      <IconInventory size={s} />
    </span>
  ),
  ai: (s) => (
    <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-violet-100 text-violet-600">
      <IconSparkles size={s} />
    </span>
  ),
  scheduler: (s) => (
    <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-amber-100 text-amber-600">
      <IconClock size={s} />
    </span>
  ),
  publisher: (s) => (
    <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-sky-100 text-sky-600">
      <IconUpload size={s} />
    </span>
  ),
  destination: (s) => (
    <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-rose-100 text-rose-600">
      <IconDestinations size={s} />
    </span>
  ),
};

const STATUS_META: Record<
  FacebookFlowVisualStatus,
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

export const DEFAULT_FACEBOOK_FLOW_STEPS: FacebookFlowStep[] = [
  { key: "source", title: "Source", subtitle: "Facebook Fanpage", status: "idle" },
  { key: "inventory", title: "Inventory", subtitle: "Videos", status: "idle" },
  { key: "ai", title: "AI Metadata", subtitle: "Title / Desc / Tags", status: "idle" },
  { key: "scheduler", title: "Scheduler", subtitle: "Slots", status: "idle" },
  { key: "publisher", title: "Publisher", subtitle: "Upload", status: "idle" },
  { key: "destination", title: "YouTube Destination", subtitle: "Channel", status: "idle" },
];

function edgeLook(
  a: FacebookFlowVisualStatus,
  b: FacebookFlowVisualStatus,
  gradientId: string,
  isActive: boolean
): FlowEdgeLook {
  // Backend active_edges remain the source of truth for real runtime work.
  // Everything else is connected-state (ambient) or dead (idle) — visual only.
  if (a === "error" || b === "error") return { kind: "failed" };
  if (isActive) return { kind: "active", gradientId };
  // not_configured or idle with no healthy upstream: static, faded out.
  if (a === "not_configured" || b === "not_configured") return { kind: "idle" };
  if (a === "idle" || b === "idle") return { kind: "idle" };
  // Healthy path (ready / partial / waiting / done, or a running node whose
  // own edge is carried by active_edges): light ambient shimmer, no pulse.
  return { kind: "ambient" };
}

function StepBox({ step }: { step: FacebookFlowStep }) {
  const status = normalizeFlowStatus(step.status);
  const meta = STATUS_META[status] ?? STATUS_META.idle;
  const icon = (STEP_ICONS[step.key] ?? STEP_ICONS.inventory)(17);

  // Use detail from step if provided, otherwise fallback to subtitle
  const displayDetail = step.detail ?? step.subtitle;

  const isRunning = status === "running";
  const isError = status === "error";

  return (
    <div
      className={`flex w-full min-w-0 items-center gap-3 rounded-2xl border bg-white p-3 shadow-[0_1px_2px_rgba(15,23,42,0.05)] transition-all duration-200 sm:p-3.5 ${
        isRunning
          ? "border-indigo-400 ring-2 ring-indigo-200"
          : isError
            ? "border-rose-400 ring-2 ring-rose-200"
            : status === "ready" || status === "partial"
              ? "border-emerald-200"
              : status === "done"
                ? "border-emerald-200"
                : status === "waiting"
                  ? "border-amber-200"
                  : "border-slate-200/90"
      }`}
      style={
        isRunning
          ? { filter: "drop-shadow(0 0 8px rgba(99,102,241,0.30))" }
          : isError
            ? { filter: "drop-shadow(0 0 8px rgba(244,63,94,0.30))" }
            : undefined
      }
    >
      <span className="shrink-0">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-extrabold tracking-tight text-slate-900">
          {step.title}
        </span>
        <span className="block truncate text-[11px] font-medium text-slate-500">{displayDetail}</span>
      </span>
      <span
        className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold ring-1 ring-inset ${meta.chip}`}
      >
        <span className="relative flex h-1.5 w-1.5">
          {meta.pulse ? (
            <span className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 ${meta.dot}`} />
          ) : null}
          <span className={`relative inline-flex h-1.5 w-1.5 rounded-full ${meta.dot}`} />
        </span>
        {meta.icon}
        {meta.label}
      </span>
    </div>
  );
}

function Connector({ d, look }: { d: string; look: FlowEdgeLook }) {
  return (
    <svg
      width={24}
      height={26}
      viewBox="0 0 24 26"
      fill="none"
      aria-hidden
      className="shrink-0"
      style={{ marginLeft: 18 }}
    >
      <FlowEdge d={d} look={look} pulseDur="1.2s" />
    </svg>
  );
}

const EDGE_KEYS: FacebookFlowActiveEdge[] = [
  "source->inventory",
  "inventory->ai_metadata",
  "ai_metadata->scheduler",
  "scheduler->publisher",
  "publisher->youtube_destination",
];

export function FacebookPipelineFlow({
  steps = DEFAULT_FACEBOOK_FLOW_STEPS,
  activeEdges = [],
}: {
  steps?: FacebookFlowStep[];
  activeEdges?: FacebookFlowActiveEdge[];
}) {
  const uid = useId().replace(/[^a-zA-Z0-9]/g, "");
  const gradientId = `fb-flow-grad-${uid}`;
  const d = vPath(12, 0, 12, 26);
  return (
    <div className="w-full min-w-0">
      <svg width={0} height={0} aria-hidden style={{ position: "absolute" }}>
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#8b5cf6" />
            <stop offset="100%" stopColor="#3b82f6" />
          </linearGradient>
        </defs>
      </svg>
      <div className="flex w-full min-w-0 flex-col items-stretch">
        {steps.map((step, idx) => (
          <div key={step.key} className="w-full min-w-0">
            <StepBox step={step} />
            {idx < steps.length - 1 ? (
              <Connector
                d={d}
                look={edgeLook(
                  normalizeFlowStatus(step.status),
                  normalizeFlowStatus(steps[idx + 1].status),
                  gradientId,
                  activeEdges.includes(EDGE_KEYS[idx]),
                )}
              />
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

export function FacebookPipelineFlowCard({
  steps,
  activeEdges,
}: {
  steps?: FacebookFlowStep[];
  activeEdges?: FacebookFlowActiveEdge[];
}) {
  return (
    <Card className="p-0">
      <div className="border-b border-slate-100 px-4 py-2.5 sm:px-5">
        <p className="text-[11px] font-extrabold uppercase tracking-[0.12em] text-slate-400">
          Facebook Pipeline Flow
        </p>
      </div>
      <div className="p-4 sm:px-5">
        <FacebookPipelineFlow steps={steps} activeEdges={activeEdges} />
      </div>
    </Card>
  );
}
