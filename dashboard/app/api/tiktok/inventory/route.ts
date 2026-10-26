import { NextResponse } from "next/server";
import { listTikTokInventory, TikTokApiError } from "@/lib/tiktok-api";

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const sourceId = searchParams.get("source_id");
    if (!sourceId) {
      return NextResponse.json({ error: "Thiếu source_id." }, { status: 400 });
    }
    const inventory = await listTikTokInventory(sourceId);
    return NextResponse.json(inventory);
  } catch (err: unknown) {
    const status = err instanceof TikTokApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không tải được inventory.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
