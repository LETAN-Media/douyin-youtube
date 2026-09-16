import { NextResponse } from "next/server";
import { generateManualMetadata } from "@/lib/api";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const result = await generateManualMetadata(body);
    return NextResponse.json(result);
  } catch (err: unknown) {
    const status = (err as { status?: number })?.status || 500;
    const message = err instanceof Error ? err.message : "Tạo metadata thất bại.";
    return NextResponse.json({ error: message }, { status });
  }
}
