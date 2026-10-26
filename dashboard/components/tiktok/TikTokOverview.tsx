"use client";

import { useState } from "react";
import type { TikTokPipelineDto, TikTokFlowState } from "@/lib/tiktok-api";
import { TikTokPipelineOrbitalView, type TikTokOrbitalNodeDatum } from "./TikTokPipelineOrbitalView";
import { TikTokFlowLive } from "./TikTokFlowLive";
import { Card } from "@/components/ui";

const ORBITAL_STEPS: Array<{
  key: keyof TikTokFlowState["steps"];
  title: string;
}> = [
  { key: "source", title: "TikTok Source" },
  { key: "inventory", title: "Inventory" },
  { key: "ai_metadata", title: "AI Metadata" },
  { key: "scheduler", title: "Scheduler" },
  { key: "publisher", title: "Publisher" },
  { key: "youtube_destination", title: "YouTube Destination" },
];

function buildDefaultOrbitalNodes(pipeline: TikTokPipelineDto): TikTokOrbitalNodeDatum[] {
  const isAuto = Boolean(pipeline.auto_publish);
  return [
    { key: "source", title: "TikTok Source", subtitle: "Đang tải dữ liệu...", status: "waiting" },
    { key: "inventory", title: "Inventory", subtitle: "Kho video TikTok", status: "idle" },
    { key: "ai_metadata", title: "AI Metadata", subtitle: "SEO Tiêu đề & Tags", status: "idle" },
    { key: "scheduler", title: "Scheduler", subtitle: isAuto ? "Auto ON" : "Auto OFF", status: isAuto ? "ready" : "idle" },
    { key: "publisher", title: "Publisher", subtitle: "Tải PhimTat & Upload", status: "idle" },
    { key: "youtube_destination", title: "YouTube Destination", subtitle: "Đang kiểm tra...", status: "waiting" },
  ];
}

function toOrbitalNodes(state: TikTokFlowState): TikTokOrbitalNodeDatum[] {
  return ORBITAL_STEPS.map((d) => ({
    key: d.key,
    title: d.title,
    subtitle: state.details?.[d.key] || "—",
    status: state.steps?.[d.key] || "idle",
  }));
}

export function TikTokOverview({
  pipeline,
  initialFlow,
  flowError = null,
  channelAvatarUrl = null,
  channelName = null,
}: {
  pipeline: TikTokPipelineDto;
  initialFlow: TikTokFlowState | null;
  flowError?: string | null;
  channelAvatarUrl?: string | null;
  channelName?: string | null;
}) {
  const [liveState, setLiveState] = useState<TikTokFlowState | null>(null);
  const flowState = liveState ?? initialFlow;
  const orbitalNodes = flowState ? toOrbitalNodes(flowState) : buildDefaultOrbitalNodes(pipeline);

  return (
    <div className="space-y-4">
      {/* Orbital Live View — Always rendered with all 6 nodes */}
      <TikTokPipelineOrbitalView
        pipelineName={pipeline.name}
        autoPublish={Boolean(pipeline.auto_publish)}
        live={Boolean(pipeline.enabled)}
        nodes={orbitalNodes}
        activeEdges={flowState?.active_edges || []}
        channelAvatarUrl={channelAvatarUrl}
        channelName={channelName}
      />

      {/* Sequential Flow & Metrics */}
      <TikTokFlowLive
        pipelineId={pipeline.id}
        initial={initialFlow}
        initialError={flowError}
        onUpdate={setLiveState}
      />

      {/* Pipeline Status Summary Footer */}
      <Card className="p-0">
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-xs text-slate-500 sm:px-5">
          <div className="flex flex-wrap items-center gap-4">
            <span className="font-semibold text-slate-700">
              Pipeline Status:{" "}
              <span className={pipeline.enabled ? "text-emerald-600" : "text-slate-500"}>
                {pipeline.enabled ? "ENABLED" : "DISABLED"}
              </span>
            </span>
            <span className="font-semibold text-slate-700">
              Auto Publish:{" "}
              <span className={pipeline.auto_publish ? "text-indigo-600" : "text-slate-500"}>
                {pipeline.auto_publish ? "ACTIVE" : "OFF"}
              </span>
            </span>
          </div>
          <div className="text-[11px] text-slate-400">
            Slug: <span className="font-mono text-slate-600">@{pipeline.slug}</span>
          </div>
        </div>
      </Card>
    </div>
  );
}
