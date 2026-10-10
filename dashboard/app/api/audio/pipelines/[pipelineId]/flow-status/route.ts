import { proxyAudio } from "@/lib/audio-proxy";

export async function GET(
  _req: Request, { params }: { params: Promise<{ pipelineId: string }> },
) {
  const { pipelineId } = await params;
  return proxyAudio(`/api/audio/pipelines/${encodeURIComponent(pipelineId)}/flow-status`);
}
