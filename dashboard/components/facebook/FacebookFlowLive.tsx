"use client";

import { useEffect, useRef, useState } from "react";
import type { FacebookFlowState } from "@/lib/facebook-api";
import {
  FacebookPipelineFlowCard,
  type FacebookFlowStep,
} from "./FacebookPipelineFlow";

const POLL_MS = 2500;

const STEP_DEFS: Array<{ key: keyof FacebookFlowState["steps"]; title: string; subtitle: string }> = [
  { key: "source", title: "Source", subtitle: "Facebook Fanpage" },
  { key: "inventory", title: "Inventory", subtitle: "Videos" },
  { key: "ai_metadata", title: "AI Metadata", subtitle: "Title / Desc / Tags" },
  { key: "scheduler", title: "Scheduler", subtitle: "Slots" },
  { key: "publisher", title: "Publisher", subtitle: "Upload" },
  { key: "youtube_destination", title: "YouTube Destination", subtitle: "Channel" },
];

function toSteps(state: FacebookFlowState): FacebookFlowStep[] {
  return STEP_DEFS.map((d) => ({
    key: d.key,
    title: d.title,
    subtitle: d.subtitle,
    status: state.steps[d.key],
  }));
}

function Metric({ label, value, tone }: { label: string; value: number; tone?: string }) {
  const cls = tone === "red" ? "text-rose-600" : tone === "amber" ? "text-amber-600" : "text-slate-900";
  return (
    <span className="flex shrink-0 items-baseline gap-1.5">
      <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400">{label}</span>
      <span className={`tnum text-[15px] font-extrabold ${cls}`}>{value}</span>
    </span>
  );
}

export function FacebookFlowLive({
  pipelineId,
  initial,
  initialError,
}: {
  pipelineId: string;
  initial: FacebookFlowState | null;
  initialError: string | null;
}) {
  const [state, setState] = useState<FacebookFlowState | null>(initial);
  const [error, setError] = useState<string | null>(initialError);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const res = await fetch(`/api/facebook/flow/${encodeURIComponent(pipelineId)}`, {
          cache: "no-store",
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as FacebookFlowState & { error?: string };
        if (data.error) throw new Error(data.error);
        if (!cancelled) {
          setState(data);
          setError(null);
        }
      } catch {
        if (!cancelled) setError("Không cập nhật được trạng thái realtime.");
      }
    }
    timer.current = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      if (timer.current) clearInterval(timer.current);
    };
  }, [pipelineId]);

  if (!state) {
    return (
      <div className="rounded-2xl border border-rose-200 bg-rose-50 p-5 text-center shadow-sm">
        <p className="text-sm font-bold text-rose-800">Không tải được trạng thái pipeline</p>
        <p className="mt-1 text-xs text-rose-600">{error ?? "Backend Facebook không phản hồi."}</p>
      </div>
    );
  }

  const live = state.live;
  return (
    <div className="space-y-3">
      {error ? (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-xs font-semibold text-amber-800 shadow-sm">
          {error} Hiển thị dữ liệu gần nhất.
        </div>
      ) : null}
      <div
        className={`flex items-center gap-x-4 gap-y-1 overflow-x-auto whitespace-nowrap rounded-2xl border border-slate-200/90 bg-white px-4 py-2 text-[13px] shadow-[0_1px_2px_rgba(15,23,42,0.05)] sm:px-5 transition-opacity ${
          error ? "opacity-70" : ""
        }`}
      >
        <span className="flex shrink-0 items-center gap-1.5 font-bold text-slate-700">
          <span className="relative flex h-2 w-2">
            <span className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 ${live ? "bg-emerald-400" : "bg-amber-400"}`} />
            <span className={`relative inline-flex h-2 w-2 rounded-full ${live ? "bg-emerald-500" : "bg-amber-500"}`} />
          </span>
          {live ? "LIVE" : "PAUSED"}
        </span>
        <Metric label="SOURCES" value={state.sources} />
        <Metric label="INVENTORY" value={state.inventory} />
        <Metric label="QUEUE" value={state.queued} tone={state.queued > 0 ? "amber" : undefined} />
        <Metric label="PUBLISHING" value={state.processing} />
        <Metric label="FAILED" value={state.failed} tone={state.failed > 0 ? "red" : undefined} />
      </div>
      <div className={error ? "opacity-70" : ""}>
        <FacebookPipelineFlowCard steps={toSteps(state)} />
      </div>
    </div>
  );
}
