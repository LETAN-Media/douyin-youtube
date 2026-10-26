import { NextResponse } from "next/server";
import { listTikTokQueue, TikTokApiError } from "@/lib/tiktok-api";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ pipelineId: string }> },
) {
  try {
    const { pipelineId } = await params;
    if (!pipelineId) {
      return NextResponse.json({ error: "Thiếu pipelineId." }, { status: 400 });
    }
    const queue = await listTikTokQueue(pipelineId);
    return NextResponse.json(queue);
  } catch (err: unknown) {
    const status = err instanceof TikTokApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không tải được hàng đợi.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
