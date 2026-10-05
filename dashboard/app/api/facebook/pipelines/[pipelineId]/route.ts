import { NextResponse } from "next/server";
import {
  FacebookApiError,
  updateFacebookPipeline,
} from "@/lib/facebook-api";

// Server-side proxy: browser calls same-origin
// PATCH /api/facebook/pipelines/{pipelineId}
// Token (FACEBOOK_ADMIN_TOKEN) never leaves the server.
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
    let body: { enabled?: unknown; auto_publish?: unknown };
    try {
      body = (await request.json()) as { enabled?: unknown; auto_publish?: unknown };
    } catch {
      return NextResponse.json(
        { error: "Body không hợp lệ.", message: "Body không hợp lệ." },
        { status: 400 },
      );
    }
    const payload: { enabled?: boolean; auto_publish?: boolean } = {};
    if (typeof body.enabled === "boolean") payload.enabled = body.enabled;
    if (typeof body.auto_publish === "boolean") payload.auto_publish = body.auto_publish;
    if (payload.enabled === undefined && payload.auto_publish === undefined) {
      return NextResponse.json(
        { error: "Cần ít nhất một field: enabled, auto_publish.", message: "Cần ít nhất một field: enabled, auto_publish." },
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
