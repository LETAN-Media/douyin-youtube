import { NextResponse } from "next/server";
import { publishManual } from "@/lib/api";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const result = await publishManual(body);
    return NextResponse.json(result, { status: 202 });
  } catch (err: unknown) {
    const status = (err as { status?: number })?.status || 500;
    const message = err instanceof Error ? err.message : "Đăng video thất bại.";
    let details: unknown = null;
    try {
      details = JSON.parse(message);
    } catch {
      details = { error: message };
    }
    return NextResponse.json(details, { status });
  }
}
