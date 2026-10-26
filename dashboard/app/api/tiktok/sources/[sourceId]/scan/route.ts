import { NextResponse } from "next/server";
import { runTikTokScan, TikTokApiError } from "@/lib/tiktok-api";

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ sourceId: string }> },
) {
  try {
    const { sourceId } = await params;
    if (!sourceId) {
      return NextResponse.json({ error: "Thiếu sourceId." }, { status: 400 });
    }
    const result = await runTikTokScan(sourceId);
    return NextResponse.json(result);
  } catch (err: unknown) {
    const status = err instanceof TikTokApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không thể bắt đầu quét video.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
