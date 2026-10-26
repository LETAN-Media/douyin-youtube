import { NextResponse } from "next/server";
import {
  createTikTokDestination,
  listAllTikTokDestinations,
  TikTokApiError,
} from "@/lib/tiktok-api";

export async function GET() {
  try {
    const destinations = await listAllTikTokDestinations();
    return NextResponse.json(destinations);
  } catch (err: unknown) {
    const status = err instanceof TikTokApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không tải được danh sách kênh.";
    return NextResponse.json({ error: message, message }, { status });
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json().catch(() => ({}));
    if (!body.pipeline_id) {
      return NextResponse.json(
        { error: "Thiếu pipeline_id.", message: "Thiếu pipeline_id." },
        { status: 400 },
      );
    }
    const created = await createTikTokDestination(body);
    return NextResponse.json(created);
  } catch (err: unknown) {
    const status = err instanceof TikTokApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không tạo được kênh đích.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
