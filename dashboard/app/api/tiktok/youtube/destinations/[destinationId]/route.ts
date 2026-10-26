import { NextResponse } from "next/server";
import {
  disconnectTikTokDestination,
  setDefaultTikTokDestination,
  toggleTikTokDestinationEnabled,
  TikTokApiError,
} from "@/lib/tiktok-api";

export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ destinationId: string }> },
) {
  try {
    const { destinationId } = await params;
    if (!destinationId) {
      return NextResponse.json({ error: "Thiếu destinationId." }, { status: 400 });
    }
    const result = await disconnectTikTokDestination(destinationId);
    return NextResponse.json(result);
  } catch (err: unknown) {
    const status = err instanceof TikTokApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không ngắt kết nối được kênh.";
    return NextResponse.json({ error: message }, { status });
  }
}

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ destinationId: string }> },
) {
  try {
    const { destinationId } = await params;
    if (!destinationId) {
      return NextResponse.json({ error: "Thiếu destinationId." }, { status: 400 });
    }
    const body = (await request.json().catch(() => ({}))) as {
      action?: "enable" | "default";
      enabled?: boolean;
      pipeline_id?: string;
    };

    if (body.action === "default" || body.pipeline_id) {
      const pipelineId = body.pipeline_id;
      if (!pipelineId) {
        return NextResponse.json({ error: "Thiếu pipeline_id để đặt mặc định." }, { status: 400 });
      }
      const updated = await setDefaultTikTokDestination(pipelineId, destinationId);
      return NextResponse.json(updated);
    }

    if (typeof body.enabled === "boolean") {
      const updated = await toggleTikTokDestinationEnabled(destinationId, body.enabled);
      return NextResponse.json(updated);
    }

    return NextResponse.json({ error: "Yêu cầu không hợp lệ." }, { status: 400 });
  } catch (err: unknown) {
    const status = err instanceof TikTokApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không cập nhật được kênh.";
    return NextResponse.json({ error: message }, { status });
  }
}
