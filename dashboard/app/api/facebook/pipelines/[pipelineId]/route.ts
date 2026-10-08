import { NextResponse } from "next/server";
import {
  FacebookApiError,
  getFacebookPipelineDetail,
  updateFacebookPipeline,
} from "@/lib/facebook-api";

// Server-side proxy: browser calls same-origin
// GET/PATCH /api/facebook/pipelines/{pipelineId}
// Token (FACEBOOK_ADMIN_TOKEN) never leaves the server.
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
    return NextResponse.json(await getFacebookPipelineDetail(pipelineId));
  } catch (err: unknown) {
    const status = err instanceof FacebookApiError ? err.status : 500;
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
    let body: { enabled?: unknown; auto_publish?: unknown; name?: unknown; youtube_upload_mode?: unknown };
    try {
      body = (await request.json()) as { enabled?: unknown; auto_publish?: unknown; name?: unknown; youtube_upload_mode?: unknown };
    } catch {
      return NextResponse.json(
        { error: "Body không hợp lệ.", message: "Body không hợp lệ." },
        { status: 400 },
      );
    }
    const payload: { enabled?: boolean; auto_publish?: boolean; name?: string; youtube_upload_mode?: string } = {};
    if (typeof body.enabled === "boolean") payload.enabled = body.enabled;
    if (typeof body.auto_publish === "boolean") payload.auto_publish = body.auto_publish;
    if (typeof body.name === "string" && body.name.trim()) payload.name = body.name.trim();
    if (typeof body.youtube_upload_mode === "string" && body.youtube_upload_mode.trim()) {
      payload.youtube_upload_mode = body.youtube_upload_mode.trim();
    }
    if (payload.enabled === undefined && payload.auto_publish === undefined && payload.name === undefined && payload.youtube_upload_mode === undefined) {
      return NextResponse.json(
        { error: "Cần ít nhất một field: enabled, auto_publish, name, youtube_upload_mode.", message: "Cần ít nhất một field: enabled, auto_publish, name, youtube_upload_mode." },
        { status: 400 },
      );
    }
    const updated = await updateFacebookPipeline(pipelineId, payload);
    return NextResponse.json(updated);
  } catch (err: unknown) {
    const status = err instanceof FacebookApiError ? err.status : 500;
    const message =
      err instanceof Error ? err.message : "Không thể cập nhật pipeline.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
