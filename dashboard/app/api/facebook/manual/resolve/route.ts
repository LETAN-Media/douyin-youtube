import { NextResponse } from "next/server";
import { FacebookApiError, resolveManualVideo } from "@/lib/facebook-api";

export async function POST(request: Request) {
  try {
    const body = (await request.json().catch(() => null)) as { url?: unknown } | null;
    if (!body || typeof body.url !== "string" || !body.url.trim()) {
      return NextResponse.json(
        { error: "Thiếu Facebook URL.", message: "Thiếu Facebook URL." },
        { status: 400 },
      );
    }
    return NextResponse.json(await resolveManualVideo(body.url.trim()));
  } catch (err: unknown) {
    const status = err instanceof FacebookApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không nhận diện được video.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
