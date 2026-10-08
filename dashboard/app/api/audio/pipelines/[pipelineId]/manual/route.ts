import { proxyAudio } from "@/lib/audio-proxy";

export async function POST(
  request: Request, { params }: { params: Promise<{ pipelineId: string }> },
) {
  const { pipelineId } = await params;
  const body = await request.json().catch(() => ({}));
  return proxyAudio(
    `/api/audio/pipelines/${encodeURIComponent(pipelineId)}/manual`,
    { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body) },
    60000,
  );
}
