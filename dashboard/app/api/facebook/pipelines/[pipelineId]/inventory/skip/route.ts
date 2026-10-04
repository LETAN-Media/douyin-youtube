import { NextResponse } from "next/server";
import { FacebookApiError, bulkSkipFacebookReels } from "@/lib/facebook-api";

export async function POST(
  request: Request,
  props: { params: Promise<{ pipelineId: string }> },
) {
  try {
    const { pipelineId } = await props.params;
    const body = await request.json();
    const reelIds: string[] = Array.isArray(body?.reel_ids) ? body.reel_ids : [];
    if (reelIds.length === 0) {
      return NextResponse.json({ error: "reel_ids trống." }, { status: 400 });
    }
    const data = await bulkSkipFacebookReels(pipelineId, reelIds);
    return NextResponse.json(data);
  } catch (err: unknown) {
    const status = err instanceof FacebookApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Bulk skip thất bại.";
    return NextResponse.json({ error: message }, { status });
  }
}
