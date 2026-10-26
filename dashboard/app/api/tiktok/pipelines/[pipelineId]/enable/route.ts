import { NextResponse } from "next/server";
import { TikTokApiError, toggleTikTokPipelineEnabled } from "@/lib/tiktok-api";

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ pipelineId: string }> },
) {
  try {
    const { pipelineId } = await params;
    if (!pipelineId) {
      return NextResponse.json({ error: "Thiếu pipelineId." }, { status: 400 });
    }
    const body = await request.json().catch(() => ({}));
    const enabled = Boolean(body.enabled);
    const updated = await toggleTikTokPipelineEnabled(pipelineId, enabled);
    return NextResponse.json(updated);
  } catch (err: unknown) {
    const status = err instanceof TikTokApiError ? err.status : 500;
    const message =
      err instanceof Error ? err.message : "Không thể cập nhật trạng thái pipeline.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
