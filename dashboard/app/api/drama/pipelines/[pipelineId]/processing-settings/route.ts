import { NextResponse } from "next/server";
import {
  DramaApiError,
  getDramaProcessingSettings,
  updateDramaProcessingSettings,
} from "@/lib/drama-api";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ pipelineId: string }> },
) {
  try {
    const { pipelineId } = await params;
    if (!pipelineId) {
      return NextResponse.json({ error: "Thiếu pipelineId." }, { status: 400 });
    }
    return NextResponse.json(await getDramaProcessingSettings(pipelineId));
  } catch (err: unknown) {
    const status = err instanceof DramaApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không tải được cài đặt.";
    return NextResponse.json({ error: message, message }, { status });
  }
}

export async function PUT(
  request: Request,
  { params }: { params: Promise<{ pipelineId: string }> },
) {
  try {
    const { pipelineId } = await params;
    if (!pipelineId) {
      return NextResponse.json({ error: "Thiếu pipelineId." }, { status: 400 });
    }
    const body = (await request.json().catch(() => null)) as Record<string, unknown> | null;
    if (!body || typeof body !== "object") {
      return NextResponse.json({ error: "Body không hợp lệ." }, { status: 400 });
    }
    const payload: Record<string, unknown> = {};
    if (typeof body.processing_mode === "string") payload.processing_mode = body.processing_mode;
    if (typeof body.merge_all_episodes === "boolean") payload.merge_all_episodes = body.merge_all_episodes;
    if (body.episodes_per_video === null || typeof body.episodes_per_video === "number") {
      payload.episodes_per_video = body.episodes_per_video;
    }
    if (body.target_language === null || typeof body.target_language === "string") {
      payload.target_language = body.target_language;
    }
    if (typeof body.subtitle_enabled === "boolean") payload.subtitle_enabled = body.subtitle_enabled;
    if (typeof body.tts_enabled === "boolean") payload.tts_enabled = body.tts_enabled;
    return NextResponse.json(await updateDramaProcessingSettings(pipelineId, payload));
  } catch (err: unknown) {
    const status = err instanceof DramaApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không lưu được cài đặt.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
