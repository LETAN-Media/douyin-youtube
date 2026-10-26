"use client";

import { useEffect, useRef, useState } from "react";
import type { TikTokFlowState, TikTokFlowStep } from "@/lib/tiktok-api";
import { TikTokPipelineFlowCard } from "./TikTokPipelineFlow";

const POLL_INTERVAL_MS = 10000;

const STEP_DEFS: Array<{ key: keyof TikTokFlowState["steps"]; title: string; subtitle: string }> = [
  { key: "source", title: "TikTok Source", subtitle: "Creator profiles" },
  { key: "inventory", title: "Inventory", subtitle: "Kho video TikTok" },
  { key: "ai_metadata", title: "AI Metadata", subtitle: "SEO Tiêu đề & Tags" },
  { key: "scheduler", title: "Scheduler", subtitle: "Lịch đăng tự động" },
  { key: "publisher", title: "Publisher", subtitle: "Tải PhimTat & Upload" },
  { key: "youtube_destination", title: "YouTube Destination", subtitle: "Kênh YouTube nhận video" },
];

function toSteps(state: TikTokFlowState): TikTokFlowStep[] {
  return STEP_DEFS.map((d) => ({
    key: d.key,
    title: d.title,
    subtitle: d.subtitle,
    status: state.steps[d.key],
    detail: state.details?.[d.key],
  }));
}

function Metric({ label, value, tone }: { label: string; value: number; tone?: string }) {
  const cls =
    tone === "rose"
      ? "text-rose-600"
      : tone === "amber"
        ? "text-amber-600"
        : tone === "indigo"
          ? "text-indigo-600"
          : "text-slate-900";

  return (
    <div className="flex flex-col">
      <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400">{label}</span>
      <span className={`text-xl font-extrabold sm:text-2xl ${cls}`}>{value}</span>
    </div>
  );
}

export function TikTokFlowLive({
  pipelineId,
  initial,
  initialError,
  onUpdate,
}: {
  pipelineId: string;
  initial: TikTokFlowState | null;
  initialError: string | null;
  onUpdate?: (state: TikTokFlowState | null) => void;
}) {
  const [state, setState] = useState<TikTokFlowState | null>(initial);
  const [error, setError] = useState<string | null>(initialError);
  const isFetchingRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const onUpdateRef = useRef(onUpdate);

  useEffect(() => {
    onUpdateRef.current = onUpdate;
  }, [onUpdate]);

  useEffect(() => {
    onUpdateRef.current?.(initial);
  }, [pipelineId, initial]);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      // Avoid duplicate overlapping fetches or polling when tab is hidden
      if (isFetchingRef.current || document.hidden) return;
      isFetchingRef.current = true;

      try {
        const res = await fetch(`/api/tiktok/flow/${encodeURIComponent(pipelineId)}`, {
          cache: "no-store",
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as TikTokFlowState & { error?: string };
        if (data.error) throw new Error(data.error);

        if (!cancelled) {
          setState(data);
          setError(null);
          onUpdateRef.current?.(data);
        }
      } catch {
        if (!cancelled) {
          // Gracefully keep previous state, don't flash error if transient
        }
      } finally {
        isFetchingRef.current = false;
      }
    }

    // Start interval
    timerRef.current = setInterval(poll, POLL_INTERVAL_MS);

    // Listen to tab visibility: pause interval when hidden, poll once immediately when back
    const handleVisibility = () => {
      if (document.hidden) {
        if (timerRef.current) {
          clearInterval(timerRef.current);
          timerRef.current = null;
        }
      } else {
        void poll();
        if (!timerRef.current) {
          timerRef.current = setInterval(poll, POLL_INTERVAL_MS);
        }
      }
    };

    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      cancelled = true;
      if (timerRef.current) clearInterval(timerRef.current);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [pipelineId]);

  if (!state && error) {
    return (
      <div className="rounded-2xl border border-rose-200 bg-rose-50 p-5 text-center shadow-sm">
        <p className="text-sm font-bold text-rose-800">Không tải được trạng thái TikTok Pipeline Flow</p>
        <p className="mt-1 text-xs text-rose-600">{error}</p>
      </div>
    );
  }

  if (!state) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-6 text-center text-xs text-slate-500 shadow-sm">
        Đang tải thông tin TikTok Pipeline Flow...
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Real-time metrics bar */}
      <div className="grid grid-cols-2 gap-3 rounded-2xl border border-slate-200/90 bg-white p-4 shadow-sm sm:grid-cols-5 sm:gap-4 sm:p-5">
        <Metric label="Sources" value={state.sources} />
        <Metric label="Kho Reels" value={state.inventory} />
        <Metric label="Đã đăng" value={state.published} tone="indigo" />
        <Metric label="Hàng đợi" value={state.queued} tone="amber" />
        <Metric label="Lỗi" value={state.failed} tone={state.failed > 0 ? "rose" : undefined} />
      </div>

      {/* Sequential Flow Diagram */}
      <TikTokPipelineFlowCard
        steps={toSteps(state)}
        activeEdges={state.active_edges}
      />
    </div>
  );
}
