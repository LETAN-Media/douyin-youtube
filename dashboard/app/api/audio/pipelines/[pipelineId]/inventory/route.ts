import { proxyAudio } from "@/lib/audio-proxy";

export async function GET(
  request: Request, { params }: { params: Promise<{ pipelineId: string }> },
) {
  const { pipelineId } = await params;
  const qs = new URL(request.url).search;
  return proxyAudio(
    `/api/audio/pipelines/${encodeURIComponent(pipelineId)}/inventory${qs}`);
}
