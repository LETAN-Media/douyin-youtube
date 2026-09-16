import { NextResponse } from "next/server";
import { getManualPublications } from "@/lib/api";

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const limit = Number(searchParams.get("limit")) || 50;
    const items = await getManualPublications(limit);
    return NextResponse.json(items);
  } catch (err: unknown) {
    const status = (err as { status?: number })?.status || 500;
    const message = err instanceof Error ? err.message : "Không tải được danh sách.";
    return NextResponse.json({ error: message }, { status });
  }
}
