"use client";

import { useEffect, useRef, useState } from "react";
import type { TikTokFlowState, TikTokFlowStep } from "@/lib/tiktok-api";
import { TikTokPipelineFlowCard } from "./TikTokPipelineFlow";
import { IconRefresh } from "@/components/icons";

const POLL_INTERVAL_MS = 10000;

const STEP_DEFS: Array<{ key: keyof TikTokFlowState["steps"]; title: string; subtitle: string }> = [
  { key: "source", title: "TikTok Source", subtitle: "Creator profiles" },
  { key: "inventory", title: "Inventory", subtitle: "Kho video TikTok" },
  { key: "ai_metadata", title: "AI Metadata", subtitle: "SEO Tiêu đề & Tags" },
  { key: "scheduler", title: "Scheduler", subtitle: "Lịch đăng tự động" },
  { key: "publisher", title: "Publisher", subtitle: "Tải PhimTat & Upload" },
  { key: "youtube_destination", title: "YouTube Destination", subtitle: "Kênh YouTube nhận video" },
];

function toSteps(state: TikTokFlowState | null): TikTokFlowStep[] {
  if (!state) {
    return STEP_DEFS.map((d) => ({
      key: d.key,
      title: d.title,
      subtitle: d.subtitle,
      status: "idle",
      detail: "Chưa cấu hình",
    }));
  }
  return STEP_DEFS.map((d) => ({
    key: d.key,
    title: d.title,
    subtitle: d.subtitle,
    status: state.steps?.[d.key] || "idle",
    detail: state.details?.[d.key] || "—",
  }));
}

function Metric({ label, value, tone }: { label: string; value: number | string; tone?: string }) {
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
  initialError?: string | null;
  onUpdate?: (state: TikTokFlowState | null) => void;
}) {
  const [state, setState] = useState<TikTokFlowState | null>(initial);
  const [error, setError] = useState<string | null>(initialError || null);
  const [retrying, setRetrying] = useState(false);
  const isFetchingRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const onUpdateRef = useRef(onUpdate);

  useEffect(() => {
    onUpdateRef.current = onUpdate;
  }, [onUpdate]);

  useEffect(() => {
    if (initial) {
      setState(initial);
      setError(null);
      onUpdateRef.current?.(initial);
    }
  }, [pipelineId, initial]);

  async function fetchFlow(force = false) {
    if ((isFetchingRef.current && !force) || (document.hidden && !force)) return;
    isFetchingRef.current = true;

    try {
      const res = await fetch(`/api/tiktok/flow/${encodeURIComponent(pipelineId)}`, {
        cache: "no-store",
      });
      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.error || `HTTP ${res.status}`);
      }
      const data = (await res.json()) as TikTokFlowState & { error?: string };
      if (data.error) throw new Error(data.error);

      setState(data);
      setError(null);
      onUpdateRef.current?.(data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Không tải được trạng thái TikTok Flow";
      // Surface error if there is no previous data or if this was an explicit user retry
      if (force || !state) {
        setError(msg);
      }
    } finally {
      isFetchingRef.current = false;
      setRetrying(false);
    }
  }

  useEffect(() => {
    let cancelled = false;

    // Immediately fetch fresh state on mount
    void fetchFlow();

    // Start polling interval
    timerRef.current = setInterval(() => {
      if (!cancelled) void fetchFlow();
    }, POLL_INTERVAL_MS);

    // Listen to tab visibility
    const handleVisibility = () => {
      if (document.hidden) {
        if (timerRef.current) {
          clearInterval(timerRef.current);
          timerRef.current = null;
        }
      } else {
        void fetchFlow();
        if (!timerRef.current) {
          timerRef.current = setInterval(() => {
            if (!cancelled) void fetchFlow();
          }, POLL_INTERVAL_MS);
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

  const handleManualRetry = () => {
    setRetrying(true);
    setError(null);
    void fetchFlow(true);
  };

  return (
    <div className="space-y-4">
      {/* Error alert with Retry button */}
      {error ? (
        <div className="flex flex-col items-center justify-between gap-3 rounded-2xl border border-rose-200 bg-rose-50/90 p-4 text-center shadow-sm sm:flex-row sm:text-left sm:p-5">
          <div className="min-w-0">
            <p className="text-sm font-bold text-rose-800">Không tải được trạng thái TikTok Pipeline Flow</p>
            <p className="mt-0.5 text-xs text-rose-600">{error}</p>
          </div>
          <button
            type="button"
            onClick={handleManualRetry}
            disabled={retrying}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-xl bg-rose-600 px-3.5 py-1.5 text-xs font-bold text-white shadow-sm hover:bg-rose-700 active:scale-95 disabled:opacity-50 transition-all"
          >
            <IconRefresh size={13} className={retrying ? "animate-spin" : ""} />
            {retrying ? "Đang tải lại…" : "Thử lại"}
          </button>
        </div>
      ) : null}

      {/* Real-time metrics bar */}
      <div className="grid grid-cols-2 gap-3 rounded-2xl border border-slate-200/90 bg-white p-4 shadow-sm sm:grid-cols-5 sm:gap-4 sm:p-5">
        <Metric label="Sources" value={state ? state.sources : "—"} />
        <Metric label="Kho Reels" value={state ? state.inventory : "—"} />
        <Metric label="Đã đăng" value={state ? state.published : "—"} tone="indigo" />
        <Metric label="Hàng đợi" value={state ? state.queued : "—"} tone="amber" />
        <Metric
          label="Lỗi"
          value={state ? state.failed : "—"}
          tone={state && state.failed > 0 ? "rose" : undefined}
        />
      </div>

      {/* Sequential Flow Diagram — Always visible with 6 nodes */}
      <TikTokPipelineFlowCard
        steps={toSteps(state)}
        activeEdges={state?.active_edges || []}
      />
    </div>
  );
}
