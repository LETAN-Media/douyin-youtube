import { NextResponse } from "next/server";
import { FacebookApiError, listManualDestinations } from "@/lib/facebook-api";

// Server-side proxy. Token (FACEBOOK_ADMIN_TOKEN) never leaves the server.
export async function GET() {
  try {
    return NextResponse.json(await listManualDestinations());
  } catch (err: unknown) {
    const status = err instanceof FacebookApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không tải được danh sách kênh.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
