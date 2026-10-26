import { NextResponse } from "next/server";
import { TikTokApiError, getTikTokFlowState } from "@/lib/tiktok-api";

// Same-origin proxy so browser can poll TikTok flow-state
// without exposing admin credentials.
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ pipelineId: string }> },
) {
  try {
    const { pipelineId } = await params;
    const state = await getTikTokFlowState(pipelineId);
    return NextResponse.json(state);
  } catch (err: unknown) {
    const status = err instanceof TikTokApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không tải được flow-state TikTok.";
    return NextResponse.json({ error: message }, { status });
  }
}
