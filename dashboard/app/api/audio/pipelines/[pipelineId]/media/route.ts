import { NextResponse } from "next/server";
import { proxyAudio } from "@/lib/audio-proxy";

export async function GET(
  request: Request, { params }: { params: Promise<{ pipelineId: string }> },
) {
  const { pipelineId } = await params;
  const qs = new URL(request.url).search;
  return proxyAudio(
    `/api/audio/pipelines/${encodeURIComponent(pipelineId)}/media${qs}`);
}

export async function POST(
  request: Request, { params }: { params: Promise<{ pipelineId: string }> },
) {
  const { pipelineId } = await params;
  const form = await request.formData().catch(() => null);
  if (!form) {
    return NextResponse.json({ error: "Form không hợp lệ." }, { status: 400 });
  }
  // Forward multipart as-is (fetch rebuilds the boundary).
  return proxyAudio(
    `/api/audio/pipelines/${encodeURIComponent(pipelineId)}/media`,
    { method: "POST", body: form as unknown as BodyInit },
    300000,
  );
}
