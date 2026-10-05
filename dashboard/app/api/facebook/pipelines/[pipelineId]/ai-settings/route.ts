import { NextResponse } from "next/server";
import {
  FacebookApiError,
  getFacebookAiSettings,
  updateFacebookAiSettings,
} from "@/lib/facebook-api";

export async function GET(
  _request: Request,
  props: { params: Promise<{ pipelineId: string }> },
) {
  try {
    const { pipelineId } = await props.params;
    const settings = await getFacebookAiSettings(pipelineId);
    return NextResponse.json(settings);
  } catch (err: unknown) {
    const status = err instanceof FacebookApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Lỗi tải AI settings.";
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
    const updated = await updateFacebookAiSettings(pipelineId, body);
    return NextResponse.json(updated);
  } catch (err: unknown) {
    const status = err instanceof FacebookApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Lỗi lưu AI settings.";
    return NextResponse.json({ error: message }, { status });
  }
}
