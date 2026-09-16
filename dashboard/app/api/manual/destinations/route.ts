import { NextResponse } from "next/server";
import { listAllDestinations } from "@/lib/api";

export async function GET() {
  try {
    const destinations = await listAllDestinations();
    return NextResponse.json(destinations);
  } catch (err: unknown) {
    const status = (err as { status?: number })?.status || 500;
    const message =
      err instanceof Error ? err.message : "Không tải được danh sách destination.";
    return NextResponse.json({ error: message }, { status });
  }
}
