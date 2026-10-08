import { Suspense } from "react";
import { Shell } from "@/components/Shell";
import { AudioApiError, listAudioPipelines } from "@/lib/audio-api";
import { AudioPipelineList } from "./AudioClient";

export default async function AudioPage() {
  let pipelines: Awaited<ReturnType<typeof listAudioPipelines>>["items"] = [];
  let error: string | null = null;
  try {
    const data = await listAudioPipelines();
    pipelines = data.items;
  } catch (err) {
    error = err instanceof AudioApiError ? err.message : "Không tải được pipelines.";
  }
  return (
    <Shell>
      <Suspense fallback={<div className="p-4 text-sm text-slate-500">Đang tải…</div>}>
        <AudioPipelineList pipelines={pipelines} error={error} />
      </Suspense>
    </Shell>
  );
}
