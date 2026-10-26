import { NextResponse } from "next/server";
import {
  createTikTokPipeline,
  listTikTokPipelines,
  TikTokApiError,
} from "@/lib/tiktok-api";

export async function GET() {
  try {
    const pipelines = await listTikTokPipelines();
    return NextResponse.json(pipelines);
  } catch (err: unknown) {
    const status = err instanceof TikTokApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Failed to list pipelines";
    return NextResponse.json({ error: message, message }, { status });
  }
}

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const result = await createTikTokPipeline(body);
    return NextResponse.json(result);
  } catch (err: unknown) {
    const status = err instanceof TikTokApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Failed to create pipeline";
    return NextResponse.json({ error: message, message }, { status });
  }
}
