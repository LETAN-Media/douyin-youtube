import { NextResponse } from "next/server";
import { DramaApiError, listDramaConnectedChannels } from "@/lib/drama-api";

export async function GET() {
  try {
    return NextResponse.json(await listDramaConnectedChannels());
  } catch (err: unknown) {
    const status = err instanceof DramaApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không tải được danh sách kênh.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
