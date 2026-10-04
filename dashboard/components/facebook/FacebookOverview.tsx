"use client";

import { Card } from "@/components/ui";
import { IconClock } from "@/components/icons";
import type { FacebookPipeline } from "@/lib/facebook-mock";
import type { FacebookFlowState } from "@/lib/facebook-api";
import { FacebookFlowLive } from "./FacebookFlowLive";

export function FacebookOverview({
  pipeline,
  pipelineId,
  initialFlow,
  flowError,
}: {
  pipeline: FacebookPipeline;
  pipelineId: string;
  initialFlow: FacebookFlowState | null;
  flowError: string | null;
}) {
  return (
    <div className="space-y-3">
      <FacebookFlowLive pipelineId={pipelineId} initial={initialFlow} initialError={flowError} />

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
