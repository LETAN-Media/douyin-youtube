import { NextResponse } from "next/server";
import { FacebookApiError, publishManualVideo } from "@/lib/facebook-api";

export async function POST(request: Request) {
  try {
    const body = (await request.json().catch(() => null)) as Record<string, unknown> | null;
    if (!body || typeof body.destination_id !== "string" || !body.destination_id) {
      return NextResponse.json(
        { error: "Thiếu destination.", message: "Thiếu destination." },
        { status: 400 },
      );
    }
    if (typeof body.source_url !== "string" || !body.source_url.trim()) {
      return NextResponse.json(
        { error: "Thiếu Facebook URL.", message: "Thiếu Facebook URL." },
        { status: 400 },
      );
    }
    if (typeof body.title !== "string" || !body.title.trim()) {
      return NextResponse.json(
        { error: "Thiếu tiêu đề.", message: "Thiếu tiêu đề." },
        { status: 400 },
      );
    }
    return NextResponse.json(
      await publishManualVideo({
        destination_id: body.destination_id,
        source_url: body.source_url,
        title: body.title,
        description: typeof body.description === "string" ? body.description : "",
        hashtags: Array.isArray(body.hashtags) ? body.hashtags.filter((t): t is string => typeof t === "string") : [],
        visibility: typeof body.visibility === "string" ? body.visibility : "public",
        publish_at: typeof body.publish_at === "string" ? body.publish_at : null,
        caption: typeof body.caption === "string" ? body.caption : null,
        thumbnail_url: typeof body.thumbnail_url === "string" ? body.thumbnail_url : null,
        duration: typeof body.duration === "number" ? body.duration : null,
        force_duplicate: body.force_duplicate === true,
      }),
      { status: 202 },
    );
  } catch (err: unknown) {
    const status = err instanceof FacebookApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không xếp được bản đăng.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
