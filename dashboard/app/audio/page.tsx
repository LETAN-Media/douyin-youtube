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
      <AudioPipelineList pipelines={pipelines} error={error} />
    </Shell>
  );
}
