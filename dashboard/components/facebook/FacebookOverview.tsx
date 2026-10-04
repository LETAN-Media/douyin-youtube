"use client";

import { Card } from "@/components/ui";
import { IconAlert, IconClock } from "@/components/icons";
import type { FacebookPipeline } from "@/lib/facebook-mock";
import {
  FacebookPipelineFlowCard,
  type FacebookFlowStep,
} from "./FacebookPipelineFlow";

function SummaryStat({ label, value, tone }: { label: string; value: number; tone?: string }) {
  const cls = tone === "red" ? "text-rose-600" : tone === "amber" ? "text-amber-600" : "text-slate-900";
  return (
    <span className="flex shrink-0 items-baseline gap-1.5">
      <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400">{label}</span>
      <span className={`tnum text-[15px] font-extrabold ${cls}`}>{value}</span>
    </span>
  );
}

export function FacebookOverview({ pipeline }: { pipeline: FacebookPipeline }) {
  const live = pipeline.enabled;
  // Frontend mock until the backend exposes per-step state.
  // Later: map API step states 1:1 into this array.
  const steps: FacebookFlowStep[] = [
    {
      key: "source",
      title: "Source",
      subtitle: "Facebook Fanpage",
      status: pipeline.sources > 0 ? "done" : "idle",
    },
    {
      key: "inventory",
      title: "Inventory",
      subtitle: "Videos",
      status: live ? "active" : "idle",
    },
    { key: "ai", title: "AI Metadata", subtitle: "Title / Desc / Tags", status: "idle" },
    { key: "scheduler", title: "Scheduler", subtitle: "Slots", status: "idle" },
    { key: "publisher", title: "Publisher", subtitle: "Upload", status: "idle" },
    { key: "destination", title: "YouTube Destination", subtitle: "Channel", status: "idle" },
  ];
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-x-4 gap-y-1 overflow-x-auto whitespace-nowrap rounded-2xl border border-slate-200/90 bg-white px-4 py-2 text-[13px] shadow-[0_1px_2px_rgba(15,23,42,0.05)] sm:px-5">
        <span className="flex shrink-0 items-center gap-1.5 font-bold text-slate-700">
          <span className="relative flex h-2 w-2">
            <span className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 ${live ? "bg-emerald-400" : "bg-amber-400"}`} />
            <span className={`relative inline-flex h-2 w-2 rounded-full ${live ? "bg-emerald-500" : "bg-amber-500"}`} />
          </span>
          {live ? "LIVE" : "PAUSED"}
        </span>
        <SummaryStat label="SOURCES" value={pipeline.sources} />
        <SummaryStat label="INVENTORY" value={pipeline.inventory} />
        <SummaryStat label="QUEUE" value={0} tone={0 > 0 ? "amber" : undefined} />
        <SummaryStat label="PUBLISHING" value={0} tone={0 > 0 ? "indigo" : undefined} />
        <SummaryStat label="FAILED" value={pipeline.failed} tone={pipeline.failed > 0 ? "red" : undefined} />
      </div>

      <FacebookPipelineFlowCard steps={steps} />

      <Card className="p-0">
        <div className="border-t border-slate-100 px-4 py-3 text-xs text-slate-500 sm:px-5">
          <div className="flex flex-wrap items-center gap-3">
            <span className="flex items-center gap-1.5">
              <IconClock size={13} />
              {pipeline.nextUpload ? `Next: ${pipeline.nextUpload}` : "Paused"}
            </span>
            <span className="font-semibold text-slate-700">Auto: {pipeline.enabled ? "ON" : "OFF"}</span>
            {pipeline.autoReason ? (
              <span className="rounded-lg bg-amber-50 px-2 py-1 text-[11px] font-bold text-amber-700">
                {pipeline.autoReason}
              </span>
            ) : null}
          </div>
        </div>
      </Card>
    </div>
  );
}
