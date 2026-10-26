import { NextResponse } from "next/server";
import { testTikTokAiSettings, TikTokApiError } from "@/lib/tiktok-api";

export async function POST(request: Request) {
  try {
    const body = await request.json().catch(() => ({}));
    if (!body.pipeline_id) {
      return NextResponse.json({ error: "Thiếu pipeline_id" }, { status: 400 });
    }
    const result = await testTikTokAiSettings(body);
    return NextResponse.json(result);
  } catch (err: unknown) {
    const status = err instanceof TikTokApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Lỗi khi chạy Test AI.";
    return NextResponse.json({ error: message }, { status });
  }
}
