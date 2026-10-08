import { proxyAudio } from "@/lib/audio-proxy";

export async function GET(
  _req: Request, { params }: { params: Promise<{ pipelineId: string }> },
) {
  const { pipelineId } = await params;
  return proxyAudio(
    `/api/audio/pipelines/${encodeURIComponent(pipelineId)}/ai-settings`);
}

export async function PUT(
  request: Request, { params }: { params: Promise<{ pipelineId: string }> },
) {
  const { pipelineId } = await params;
  const body = await request.json().catch(() => ({}));
  return proxyAudio(
    `/api/audio/pipelines/${encodeURIComponent(pipelineId)}/ai-settings`,
    { method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body) });
}
