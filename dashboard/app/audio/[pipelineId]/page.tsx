import { Shell } from "@/components/Shell";
import { AudioApiError, getAudioPipeline, type AudioPipelineDto } from "@/lib/audio-api";
import { AudioPipelineClient } from "./AudioPipelineClient";

const AUTO_TABS = [
  "overview", "sources", "inventory", "media", "processing",
  "ai", "youtube", "scheduler", "manual", "history",
] as const;

const MANUAL_TABS = [
  "manual", "media", "processing", "ai", "youtube", "history",
] as const;

export default async function AudioPipelinePage({
  params, searchParams,
}: {
  params: Promise<{ pipelineId: string }>;
  searchParams: Promise<{ tab?: string }>;
}) {
  const { pipelineId } = await params;
  const { tab } = await searchParams;
  let pipeline: AudioPipelineDto | null = null;
  let error: string | null = null;
  try {
    pipeline = await getAudioPipeline(pipelineId);
  } catch (err) {
    error = err instanceof AudioApiError ? err.message : "Không tải được pipeline.";
  }

  if (!pipeline) {
    return (
      <Shell>
        <p className="rounded-2xl bg-rose-50 px-4 py-3 text-sm font-semibold text-rose-700">
          {error || "Không tải được pipeline."}
        </p>
      </Shell>
    );
  }

  const isManual = pipeline.pipeline_type === "manual";
  let initialTab: string;
  if (isManual) {
    initialTab = MANUAL_TABS.includes(tab as (typeof MANUAL_TABS)[number])
      ? (tab as string)
      : "manual";
  } else {
    initialTab = AUTO_TABS.includes(tab as (typeof AUTO_TABS)[number])
      ? (tab as string)
      : "overview";
  }

  return (
    <Shell>
      <AudioPipelineClient pipeline={pipeline} initialTab={initialTab} />
    </Shell>
  );
}
