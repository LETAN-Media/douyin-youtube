import { NextResponse } from "next/server";
import { DramaApiError, listDramaPipelineDestinations } from "@/lib/drama-api";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ pipelineId: string }> },
) {
  try {
    const { pipelineId } = await params;
    if (!pipelineId) {
      return NextResponse.json({ error: "Thiếu pipelineId." }, { status: 400 });
    }
    return NextResponse.json(await listDramaPipelineDestinations(pipelineId));
  } catch (err: unknown) {
    const status = err instanceof DramaApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không tải được destinations.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
