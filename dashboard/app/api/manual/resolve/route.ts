import { NextResponse } from "next/server";
import { resolveManualUrl } from "@/lib/api";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const input = String(body.input ?? "").trim();
    if (!input) {
      return NextResponse.json(
        { error: "Vui lòng nhập link hoặc nội dung Douyin." },
        { status: 400 },
      );
    }
    const result = await resolveManualUrl(input);
    return NextResponse.json(result);
  } catch (err: unknown) {
    const status = (err as { status?: number })?.status || 500;
    const message = err instanceof Error ? err.message : "Resolve thất bại.";
    return NextResponse.json({ error: message }, { status });
  }
}
