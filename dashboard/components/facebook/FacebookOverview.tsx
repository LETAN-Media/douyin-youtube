"use client";

import { Card } from "@/components/ui";
import { IconAlert, IconClock } from "@/components/icons";
import type { FacebookPipeline } from "@/lib/facebook-mock";

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

      <Card className="p-0">
        <div className="border-b border-slate-100 px-4 py-2.5 sm:px-5">
          <p className="text-[11px] font-extrabold uppercase tracking-[0.12em] text-slate-400">
            FACEBOOK PIPELINE FLOW
          </p>
        </div>
        <div className="flex flex-col gap-1 p-4 sm:flex-row sm:items-center sm:justify-between sm:gap-0 sm:px-5">
          {[
            { label: "SOURCE", sub: "Facebook Fanpage" },
            { label: "INVENTORY", sub: "Videos" },
            { label: "AI METADATA", sub: "Title / Desc / Tags" },
            { label: "SCHEDULER", sub: "Slots" },
            { label: "PUBLISHER", sub: "Upload" },
            { label: "YOUTUBE DESTINATION", sub: "Channel" },
          ].map((step, idx) => (
            <div key={step.label} className="flex items-center gap-2 sm:flex-col sm:items-center sm:gap-1">
              <span className="text-[11px] font-black uppercase tracking-wider text-slate-900">{step.label}</span>
              <span className="text-[11px] font-medium text-slate-500">{step.sub}</span>
              {idx < 5 ? (
                <span className="hidden text-slate-300 sm:inline">↓</span>
              ) : null}
            </div>
          ))}
        </div>
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
