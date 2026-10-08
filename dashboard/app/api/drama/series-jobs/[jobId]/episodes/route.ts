import { NextResponse } from "next/server";
import { DramaApiError, listDramaJobEpisodes } from "@/lib/drama-api";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ jobId: string }> },
) {
  try {
    const { jobId } = await params;
    if (!jobId) return NextResponse.json({ error: "Thiếu jobId." }, { status: 400 });
    return NextResponse.json(await listDramaJobEpisodes(jobId));
  } catch (err: unknown) {
    const status = err instanceof DramaApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không tải được episodes.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
