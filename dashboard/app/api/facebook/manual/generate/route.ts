import { NextResponse } from "next/server";
import { FacebookApiError, generateManualMetadata } from "@/lib/facebook-api";

export async function POST(request: Request) {
  try {
    const body = (await request.json().catch(() => null)) as {
      destination_id?: unknown;
      caption?: unknown;
      source_url?: unknown;
    } | null;
    if (!body || typeof body.destination_id !== "string" || !body.destination_id) {
      return NextResponse.json(
        { error: "Thiếu destination.", message: "Thiếu destination." },
        { status: 400 },
      );
    }
    return NextResponse.json(
      await generateManualMetadata({
        destination_id: body.destination_id,
        caption: typeof body.caption === "string" ? body.caption : null,
        source_url: typeof body.source_url === "string" ? body.source_url : null,
      }),
    );
  } catch (err: unknown) {
    const status = err instanceof FacebookApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "AI không tạo được metadata.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
