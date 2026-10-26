import { NextResponse } from "next/server";
import { startTikTokOAuth, TikTokApiError } from "@/lib/tiktok-api";

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as {
      pipeline_id?: string;
      pipelineId?: string;
      destination_id?: string;
      destinationId?: string;
      return_to?: string;
    };
    const pipelineId = body.pipeline_id || body.pipelineId;
    if (!pipelineId) {
      return NextResponse.json({ error: "Thiếu pipeline_id." }, { status: 400 });
    }
    const destinationId = body.destination_id || body.destinationId;
    const data = await startTikTokOAuth(
      pipelineId,
      destinationId,
      typeof body.return_to === "string" ? body.return_to : undefined,
    );
    return NextResponse.json(data);
  } catch (err: unknown) {
    const status = err instanceof TikTokApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không bắt đầu được OAuth.";
    return NextResponse.json({ error: message }, { status });
  }
}
