import { NextResponse } from "next/server";
import { listTikTokAiModels, TikTokApiError } from "@/lib/tiktok-api";

export async function GET() {
  try {
    const data = await listTikTokAiModels();
    return NextResponse.json(data);
  } catch (err: unknown) {
    const status = err instanceof TikTokApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Lỗi tải danh sách AI models.";
    return NextResponse.json({ error: message }, { status });
  }
}
