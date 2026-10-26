import { NextResponse } from "next/server";
import {
  createTikTokDestination,
  listTikTokDestinations,
  TikTokApiError,
} from "@/lib/tiktok-api";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ pipelineId: string }> },
) {
  try {
    const { pipelineId } = await params;
    if (!pipelineId) {
      return NextResponse.json({ error: "Thiếu pipelineId." }, { status: 400 });
    }
    const list = await listTikTokDestinations(pipelineId);
    return NextResponse.json(list);
  } catch (err: unknown) {
    const status = err instanceof TikTokApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không tải được danh sách kênh.";
    return NextResponse.json({ error: message, message }, { status });
  }
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ pipelineId: string }> },
) {
  try {
    const { pipelineId } = await params;
    if (!pipelineId) {
      return NextResponse.json({ error: "Thiếu pipelineId." }, { status: 400 });
    }
    const body = (await request.json().catch(() => ({}))) as {
      visibility?: string;
      enabled?: boolean;
      channel_name?: string;
    };
    const created = await createTikTokDestination({
      pipeline_id: pipelineId,
      visibility: body.visibility || "public",
      enabled: body.enabled !== false,
      channel_name: body.channel_name,
    });
    return NextResponse.json(created, { status: 201 });
  } catch (err: unknown) {
    const status = err instanceof TikTokApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không tạo được kênh đích.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
