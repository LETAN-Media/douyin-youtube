"use client";

import { Card } from "@/components/ui";
import type { FacebookPipelineDto } from "@/lib/facebook-api";
import type { FacebookFlowState } from "@/lib/facebook-api";
import { FacebookFlowLive } from "./FacebookFlowLive";

export function FacebookOverview({
  pipeline,
  pipelineId,
  initialFlow,
  flowError,
}: {
  pipeline: FacebookPipelineDto;
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
            <span className="font-semibold text-slate-700">Auto: {pipeline.enabled ? "ON" : "OFF"}</span>
            <span className="font-semibold text-slate-700">
              Auto publish: {pipeline.auto_publish ? "ON" : "OFF"}
            </span>
          </div>
        </div>
      </Card>
    </div>
  );
}
