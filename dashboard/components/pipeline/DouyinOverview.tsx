"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui";
import type { Pipeline } from "@/lib/types";
import type { FlowState, FlowProcessor } from "@/lib/types";
import { PipelineOrbitalView, type OrbitalNodeDatum } from "@/components/facebook/PipelineOrbitalView";

const PROCESSOR_KEYS = ["inventory", "ai", "scheduler", "publisher"] as const;
const PROCESSOR_LABELS: Record<string, string> = {
  inventory: "Inventory",
  ai: "AI Metadata",
  scheduler: "Scheduler",
  publisher: "Publisher",
};

function toOrbitalNodes(state: FlowState): OrbitalNodeDatum[] {
  return PROCESSOR_KEYS.map((key) => {
    const proc = state.processors.find((p) => p.key === key);
    return {
      key,
      title: PROCESSOR_LABELS[key] ?? key,
      subtitle: proc?.detail ?? "—",
      status: proc?.state ?? "idle",
    };
  });
}

export function DouyinOverview({
  pipeline,
  pipelineId,
  initialFlow,
  flowError,
}: {
  pipeline: Pipeline;
  pipelineId: string;
  initialFlow: FlowState | null;
  flowError: string | null;
}) {
  const [flowState, setFlowState] = useState<FlowState | null>(initialFlow);

  // Poll for live updates
  useEffect(() => {
    let stop = false;
    let id: ReturnType<typeof setInterval>;
    const poll = async () => {
      try {
        const res = await fetch(`/api/pipelines/${encodeURIComponent(pipelineId)}/flow-state`, {
          cache: "no-store",
        });
        if (!res.ok) return;
        const data = (await res.json()) as FlowState | null;
        if (data && !stop) setFlowState(data);
      } catch {
        // Non-fatal
      }
    };
    const start = (ms: number) => {
      clearInterval(id);
      id = setInterval(poll, ms);
    };
    const onVis = () => {
      if (document.hidden) start(15000);
      else {
        start(3000);
        void poll();
      }
    };
    document.addEventListener("visibilitychange", onVis);
    start(document.hidden ? 15000 : 3000);
    return () => {
      stop = true;
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [pipelineId]);

  return (
    <div className="space-y-3">
      {flowState ? (
        <PipelineOrbitalView
          pipelineName={pipeline.name}
          nodes={toOrbitalNodes(flowState)}
          activeEdges={flowState.active_routes?.map((r) => {
            const dest = flowState.destinations.find((d) => d.id === r.destination_id);
            if (dest) return `source->${dest.id}`;
            return "";
          }).filter(Boolean) || []}
          height={380}
          channelName={pipeline.name}
        />
      ) : null}

      <Card className="p-0">
        <div className="border-t border-slate-100 px-4 py-3 text-xs text-slate-500 sm:px-5">
          <div className="flex flex-wrap items-center gap-3">
            <span className="font-semibold text-slate-700">Auto: {pipeline.enabled ? "ON" : "OFF"}</span>
            <span className="font-semibold text-slate-700">
              Auto publish: {pipeline.enabled ? "ON" : "OFF"}
            </span>
          </div>
        </div>
      </Card>
    </div>
  );
}