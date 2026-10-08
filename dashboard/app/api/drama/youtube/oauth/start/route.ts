import { NextResponse } from "next/server";
import { DramaApiError, startDramaYoutubeOAuth } from "@/lib/drama-api";

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const pipelineId = searchParams.get("pipeline_id") ?? "";
    if (!pipelineId) {
      return NextResponse.json({ error: "Thiếu pipeline_id." }, { status: 400 });
    }
    return NextResponse.json(
      await startDramaYoutubeOAuth(pipelineId, searchParams.get("visibility") ?? undefined),
    );
  } catch (err: unknown) {
    const status = err instanceof DramaApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không bắt đầu được OAuth.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
