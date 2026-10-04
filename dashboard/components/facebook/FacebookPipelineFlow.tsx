"use client";

import { useId } from "react";
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

// Visual pipeline flow for a Facebook pipeline.
// Data-driven: pass `steps` mapped 1:1 from GET flow-state.
// Backend statuses "running"/"not_configured" normalize to the existing
// visual states (active/idle) so the UI system stays unchanged.
export type FacebookFlowStatus = "idle" | "active" | "done" | "error";
export type FacebookFlowBackendStatus =
  | FacebookFlowStatus
  | "running"
  | "not_configured";

export type FacebookFlowStep = {
  key: string;
  title: string;
  subtitle: string;
  status: FacebookFlowStatus | FacebookFlowBackendStatus;
};

/** Backend -> visual mapping (single place, unit-testable via build). */
export function normalizeFlowStatus(s: string): FacebookFlowStatus {
  if (s === "running" || s === "active") return "active";
  if (s === "done") return "done";
  if (s === "error") return "error";
  return "idle"; // idle + not_configured + unknown -> gray
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

export const DEFAULT_FACEBOOK_FLOW_STEPS: FacebookFlowStep[] = [
  { key: "source", title: "Source", subtitle: "Facebook Fanpage", status: "done" },
  { key: "inventory", title: "Inventory", subtitle: "Videos", status: "active" },
  { key: "ai", title: "AI Metadata", subtitle: "Title / Desc / Tags", status: "idle" },
  { key: "scheduler", title: "Scheduler", subtitle: "Slots", status: "idle" },
  { key: "publisher", title: "Publisher", subtitle: "Upload", status: "idle" },
  { key: "destination", title: "YouTube Destination", subtitle: "Channel", status: "idle" },
];

const STATUS_META: Record<
  FacebookFlowStatus,
  { label: string; chip: string; dot: string; pulse: boolean; icon: React.ReactNode }
> = {
  idle: {
    label: "Idle",
    chip: "bg-slate-100 text-slate-600 ring-slate-200",
    dot: "bg-slate-400",
    pulse: false,
    icon: null,
  },
  active: {
    label: "Running",
    chip: "bg-indigo-50 text-indigo-700 ring-indigo-200",
    dot: "bg-indigo-500",
    pulse: true,
    icon: null,
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
};

function edgeLook(a: FacebookFlowStatus, b: FacebookFlowStatus, gradientId: string): FlowEdgeLook {
  if (a === "error" || b === "error") return { kind: "failed" };
  if (a === "active" || b === "active") return { kind: "active", gradientId };
  if (a === "done" && b === "done") return { kind: "faded" };
  if (a === "done") return { kind: "active", gradientId };
  return { kind: "idle" };
}

function StepBox({ step }: { step: FacebookFlowStep }) {
  const status = normalizeFlowStatus(step.status);
  const meta = STATUS_META[status];
  const icon = (STEP_ICONS[step.key] ?? STEP_ICONS.inventory)(17);
  return (
    <div
      className={`flex w-full min-w-0 items-center gap-3 rounded-2xl border bg-white p-3 shadow-[0_1px_2px_rgba(15,23,42,0.05)] transition-all duration-200 sm:p-3.5 ${
        status === "active"
          ? "border-indigo-400 ring-2 ring-indigo-200"
          : status === "error"
            ? "border-rose-400 ring-2 ring-rose-200"
            : status === "done"
              ? "border-emerald-200"
              : "border-slate-200/90"
      }`}
      style={
        status === "active"
          ? { filter: "drop-shadow(0 0 8px rgba(99,102,241,0.30))" }
          : status === "error"
            ? { filter: "drop-shadow(0 0 8px rgba(244,63,94,0.30))" }
            : undefined
      }
    >
      <span className="shrink-0">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-extrabold tracking-tight text-slate-900">
          {step.title}
        </span>
        <span className="block truncate text-[11px] font-medium text-slate-500">{step.subtitle}</span>
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

export function FacebookPipelineFlow({
  steps = DEFAULT_FACEBOOK_FLOW_STEPS,
}: {
  steps?: FacebookFlowStep[];
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
                )}
              />
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

export function FacebookPipelineFlowCard({ steps }: { steps?: FacebookFlowStep[] }) {
  return (
    <Card className="p-0">
      <div className="border-b border-slate-100 px-4 py-2.5 sm:px-5">
        <p className="text-[11px] font-extrabold uppercase tracking-[0.12em] text-slate-400">
          Facebook Pipeline Flow
        </p>
      </div>
      <div className="p-4 sm:px-5">
        <FacebookPipelineFlow steps={steps} />
      </div>
    </Card>
  );
}
