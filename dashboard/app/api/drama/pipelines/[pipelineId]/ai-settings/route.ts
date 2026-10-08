import { NextResponse } from "next/server";
import {
  DramaApiError,
  getDramaAiSettings,
  updateDramaAiSettings,
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
    return NextResponse.json(await getDramaAiSettings(pipelineId));
  } catch (err: unknown) {
    const status = err instanceof DramaApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không tải được cài đặt AI.";
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
    if (typeof body.enabled === "boolean") payload.enabled = body.enabled;
    if (typeof body.language === "string") payload.language = body.language;
    if (typeof body.generate_title === "boolean") payload.generate_title = body.generate_title;
    if (typeof body.generate_description === "boolean")
      payload.generate_description = body.generate_description;
    if (typeof body.generate_hashtags === "boolean")
      payload.generate_hashtags = body.generate_hashtags;
    if (body.system_prompt === null || typeof body.system_prompt === "string")
      payload.system_prompt = body.system_prompt;
    if (body.title_template === null || typeof body.title_template === "string")
      payload.title_template = body.title_template;
    if (body.description_template === null || typeof body.description_template === "string")
      payload.description_template = body.description_template;
    if (body.locked_hashtags === null || Array.isArray(body.locked_hashtags) || typeof body.locked_hashtags === "string")
      payload.locked_hashtags = body.locked_hashtags;
    if (body.model_override === null || typeof body.model_override === "string")
      payload.model_override = body.model_override;
    if (typeof body.expected_config_version === "number")
      payload.expected_config_version = body.expected_config_version;
    return NextResponse.json(await updateDramaAiSettings(pipelineId, payload));
  } catch (err: unknown) {
    const status = err instanceof DramaApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không lưu được cài đặt AI.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
