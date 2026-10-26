import { NextResponse } from "next/server";
import {
  getTikTokAiSettings,
  updateTikTokAiSettings,
  TikTokApiError,
} from "@/lib/tiktok-api";

export async function GET(
  _request: Request,
  props: { params: Promise<{ pipelineId: string }> },
) {
  try {
    const { pipelineId } = await props.params;
    const settings = await getTikTokAiSettings(pipelineId);
    return NextResponse.json(settings);
  } catch (err: unknown) {
    const status = err instanceof TikTokApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Lỗi tải TikTok AI settings.";
    return NextResponse.json({ error: message }, { status });
  }
}

export async function PUT(
  request: Request,
  props: { params: Promise<{ pipelineId: string }> },
) {
  try {
    const { pipelineId } = await props.params;
    const body = await request.json();
    const updated = await updateTikTokAiSettings(pipelineId, body);
    return NextResponse.json(updated);
  } catch (err: unknown) {
    const status = err instanceof TikTokApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Lỗi lưu TikTok AI settings.";
    return NextResponse.json({ error: message }, { status });
  }
}
