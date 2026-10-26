import { NextResponse } from "next/server";
import { createTikTokSource, TikTokApiError } from "@/lib/tiktok-api";

export async function POST(request: Request) {
  try {
    const body = await request.json().catch(() => ({}));
    const rawInput = body.username || body.source_url || body.url || body.handle;
    if (!body.pipeline_id || !rawInput) {
      return NextResponse.json(
        { error: "pipeline_id và username / URL TikTok là bắt buộc." },
        { status: 400 },
      );
    }
    const source = await createTikTokSource({
      pipeline_id: body.pipeline_id,
      username: String(rawInput).trim(),
      display_name: body.display_name?.trim() || undefined,
      source_url: body.source_url?.trim() || undefined,
    });
    return NextResponse.json(source, { status: 201 });
  } catch (err: unknown) {
    const status = err instanceof TikTokApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không thể tạo nguồn TikTok.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
