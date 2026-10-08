import { NextResponse } from "next/server";
import { DramaApiError, previewDramaAiMetadata } from "@/lib/drama-api";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ pipelineId: string }> },
) {
  try {
    const { pipelineId } = await params;
    if (!pipelineId) {
      return NextResponse.json({ error: "Thiếu pipelineId." }, { status: 400 });
    }
    const body = (await request.json().catch(() => null)) as Record<string, unknown> | null;
    const payload: Record<string, unknown> = {
      series_id: typeof body?.series_id === "string" ? body.series_id : null,
      job_id: typeof body?.job_id === "string" ? body.job_id : null,
      language: typeof body?.language === "string" ? body.language : null,
      force_regenerate: body?.force_regenerate === true,
    };
    return NextResponse.json(await previewDramaAiMetadata(pipelineId, payload));
  } catch (err: unknown) {
    const status = err instanceof DramaApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không tạo thử được metadata.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
