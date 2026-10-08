import { Shell } from "@/components/Shell";
import { AudioApiError, getAudioPipeline } from "@/lib/audio-api";
import { AudioPipelineClient } from "./AudioPipelineClient";

const TABS = ["overview", "sources", "inventory", "media", "processing",
  "ai", "youtube", "scheduler", "manual", "history"] as const;

export default async function AudioPipelinePage({
  params, searchParams,
}: {
  params: Promise<{ pipelineId: string }>;
  searchParams: Promise<{ tab?: string }>;
}) {
  const { pipelineId } = await params;
  const { tab } = await searchParams;
  const initialTab = TABS.includes(tab as (typeof TABS)[number])
    ? (tab as (typeof TABS)[number]) : "overview";
  try {
    const pipeline = await getAudioPipeline(pipelineId);
    return (
      <Shell>
        <AudioPipelineClient pipeline={pipeline} initialTab={initialTab} />
      </Shell>
    );
  } catch (err) {
    return (
      <Shell>
        <p className="rounded-2xl bg-rose-50 px-4 py-3 text-sm font-semibold text-rose-700">
          {err instanceof AudioApiError ? err.message : "Không tải được pipeline."}
        </p>
      </Shell>
    );
  }
}
