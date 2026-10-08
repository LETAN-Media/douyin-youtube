import { proxyAudio } from "@/lib/audio-proxy";

export async function POST(request: Request) {
  const { searchParams } = new URL(request.url);
  const pipelineId = searchParams.get("pipeline_id") ?? "";
  if (!pipelineId) {
    const { NextResponse } = await import("next/server");
    return NextResponse.json({ error: "Thiếu pipeline_id." }, { status: 400 });
  }
  return proxyAudio(
    `/api/audio/youtube/oauth/start?pipeline_id=${encodeURIComponent(pipelineId)}`,
    { method: "POST" });
}
