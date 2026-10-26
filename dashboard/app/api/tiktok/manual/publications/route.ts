import { NextResponse } from "next/server";
import {
  getTikTokManualPublication,
  listTikTokManualPublications,
  TikTokApiError,
} from "@/lib/tiktok-api";

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const pubId = searchParams.get("pub_id") || searchParams.get("id");
    if (pubId) {
      const pub = await getTikTokManualPublication(pubId);
      return NextResponse.json(pub);
    }

    const pipelineId = searchParams.get("pipeline_id");
    const destinationId = searchParams.get("destination_id");
    if (!pipelineId || !destinationId) {
      return NextResponse.json(
        { error: "Thiếu pipeline_id hoặc destination_id.", message: "Thiếu pipeline_id hoặc destination_id." },
        { status: 400 },
      );
    }

    const publications = await listTikTokManualPublications(pipelineId, destinationId);
    return NextResponse.json(publications);
  } catch (err: unknown) {
    const status = err instanceof TikTokApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không tải được danh sách bản đăng.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
