import { NextResponse } from "next/server";
import { resolveTikTokManualVideo, TikTokApiError } from "@/lib/tiktok-api";

export async function POST(request: Request) {
  try {
    const body = (await request.json().catch(() => null)) as { url?: unknown; source_url?: unknown } | null;
    const rawUrl = body?.url || body?.source_url;
    if (typeof rawUrl !== "string" || !rawUrl.trim()) {
      return NextResponse.json(
        { error: "Thiếu TikTok URL.", message: "Thiếu TikTok URL." },
        { status: 400 },
      );
    }
    const result = await resolveTikTokManualVideo(rawUrl.trim());
    return NextResponse.json(result);
  } catch (err: unknown) {
    const status = err instanceof TikTokApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không nhận diện được video TikTok.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
