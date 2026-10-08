import { NextResponse } from "next/server";
import { DramaApiError, resetDramaAiSettings } from "@/lib/drama-api";

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ pipelineId: string }> },
) {
  try {
    const { pipelineId } = await params;
    if (!pipelineId) {
      return NextResponse.json({ error: "Thiếu pipelineId." }, { status: 400 });
    }
    return NextResponse.json(await resetDramaAiSettings(pipelineId));
  } catch (err: unknown) {
    const status = err instanceof DramaApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không khôi phục được cài đặt AI.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
