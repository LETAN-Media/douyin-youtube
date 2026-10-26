import { NextResponse } from "next/server";
import { TikTokApiError, toggleTikTokAutoPublish } from "@/lib/tiktok-api";

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ pipelineId: string }> },
) {
  try {
    const { pipelineId } = await params;
    if (!pipelineId) {
      return NextResponse.json(
        { error: "Thiếu pipelineId.", message: "Thiếu pipelineId." },
        { status: 400 },
      );
    }
    const body = await request.json().catch(() => ({}));
    const autoPublish = Boolean(body.auto_publish);
    const updated = await toggleTikTokAutoPublish(pipelineId, autoPublish);
    return NextResponse.json(updated);
  } catch (err: unknown) {
    const status = err instanceof TikTokApiError ? err.status : 500;
    const message =
      err instanceof Error ? err.message : "Không thể cập nhật Auto Publish.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
