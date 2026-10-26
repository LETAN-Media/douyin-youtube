import { NextResponse } from "next/server";
import { publishTikTokManualVideo, TikTokApiError } from "@/lib/tiktok-api";

export async function POST(request: Request) {
  try {
    const body = (await request.json().catch(() => null)) as Record<string, unknown> | null;
    if (!body || typeof body.pipeline_id !== "string" || !body.pipeline_id) {
      return NextResponse.json(
        { error: "Thiếu pipeline_id.", message: "Thiếu pipeline_id." },
        { status: 400 },
      );
    }
    if (typeof body.destination_id !== "string" || !body.destination_id) {
      return NextResponse.json(
        { error: "Thiếu destination_id.", message: "Thiếu destination_id." },
        { status: 400 },
      );
    }
    if (typeof body.source_url !== "string" || !body.source_url.trim()) {
      return NextResponse.json(
        { error: "Thiếu TikTok URL.", message: "Thiếu TikTok URL." },
        { status: 400 },
      );
    }

    const hashtags = Array.isArray(body.hashtags)
      ? body.hashtags.filter((t): t is string => typeof t === "string")
      : typeof body.hashtags === "string"
      ? (body.hashtags as string).split(/[,\s]+/).filter(Boolean).map(h => h.startsWith("#") ? h : `#${h}`)
      : [];

    const result = await publishTikTokManualVideo({
      pipeline_id: body.pipeline_id,
      destination_id: body.destination_id,
      source_url: body.source_url.trim(),
      caption: typeof body.caption === "string" ? body.caption : null,
      youtube_title: typeof body.title === "string" ? body.title : typeof body.youtube_title === "string" ? body.youtube_title : undefined,
      youtube_description: typeof body.description === "string" ? body.description : typeof body.youtube_description === "string" ? body.youtube_description : undefined,
      hashtags,
      visibility: typeof body.visibility === "string" ? body.visibility : "public",
      publish_at: typeof body.publish_at === "string" ? body.publish_at : null,
    });

    return NextResponse.json(result, { status: 202 });
  } catch (err: unknown) {
    const status = err instanceof TikTokApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không xếp được bản đăng TikTok.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
