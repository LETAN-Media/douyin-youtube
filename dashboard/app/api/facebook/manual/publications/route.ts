import { NextResponse } from "next/server";
import { FacebookApiError, listManualPublications } from "@/lib/facebook-api";

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    return NextResponse.json(
      await listManualPublications({
        destination_id: searchParams.get("destination_id") ?? undefined,
        limit: searchParams.get("limit") ? Number(searchParams.get("limit")) : undefined,
        offset: searchParams.get("offset") ? Number(searchParams.get("offset")) : undefined,
      }),
    );
  } catch (err: unknown) {
    const status = err instanceof FacebookApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không tải được lịch sử.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
