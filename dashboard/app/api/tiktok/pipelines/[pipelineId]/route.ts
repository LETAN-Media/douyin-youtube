import { NextResponse } from "next/server";
import {
  getTikTokPipeline,
  updateTikTokPipeline,
  TikTokApiError,
} from "@/lib/tiktok-api";

export async function GET(
  _request: Request,
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
    const pipeline = await getTikTokPipeline(pipelineId);
    return NextResponse.json(pipeline);
  } catch (err: unknown) {
    const status = err instanceof TikTokApiError ? err.status : 500;
    const message =
      err instanceof Error ? err.message : "Không tải được pipeline.";
    return NextResponse.json({ error: message, message }, { status });
  }
}

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
    const updated = await updateTikTokPipeline(pipelineId, body);
    return NextResponse.json(updated);
  } catch (err: unknown) {
    const status = err instanceof TikTokApiError ? err.status : 500;
    const message =
      err instanceof Error ? err.message : "Không thể cập nhật pipeline.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
