"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui";
import type { FacebookPipelineDto } from "@/lib/facebook-api";
import type { FacebookFlowState } from "@/lib/facebook-api";
import { FacebookFlowLive } from "./FacebookFlowLive";
import {
  FACEBOOK_PIPELINE_UPDATED_EVENT,
  type FacebookPipelineFlags,
} from "./FacebookPipelineToggles";

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
  const [enabled, setEnabled] = useState(pipeline.enabled);
  const [autoPublish, setAutoPublish] = useState(pipeline.auto_publish);

  // Sync instantly when the header toggle updates the pipeline,
  // without waiting for a full page reload.
  useEffect(() => {
    setEnabled(pipeline.enabled);
    setAutoPublish(pipeline.auto_publish);
  }, [pipeline.enabled, pipeline.auto_publish]);

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<FacebookPipelineFlags>).detail;
      if (!detail) return;
      setEnabled(detail.enabled);
      setAutoPublish(detail.auto_publish);
    };
    window.addEventListener(FACEBOOK_PIPELINE_UPDATED_EVENT, handler);
    return () => window.removeEventListener(FACEBOOK_PIPELINE_UPDATED_EVENT, handler);
  }, []);

  return (
    <div className="space-y-3">
      <FacebookFlowLive pipelineId={pipelineId} initial={initialFlow} initialError={flowError} />

      <Card className="p-0">
        <div className="border-t border-slate-100 px-4 py-3 text-xs text-slate-500 sm:px-5">
          <div className="flex flex-wrap items-center gap-3">
            <span className="font-semibold text-slate-700">Auto: {enabled ? "ON" : "OFF"}</span>
            <span className="font-semibold text-slate-700">
              Auto publish: {autoPublish ? "ON" : "OFF"}
            </span>
          </div>
        </div>
      </Card>
    </div>
  );
}
