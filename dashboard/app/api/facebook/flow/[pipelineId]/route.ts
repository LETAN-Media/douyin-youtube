import { NextResponse } from "next/server";
import { FacebookApiError, getFacebookFlowState } from "@/lib/facebook-api";

// Same-origin proxy so the browser can poll flow-state every few seconds
// without ever seeing FACEBOOK_ADMIN_TOKEN.
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ pipelineId: string }> },
) {
  try {
    const { pipelineId } = await params;
    const state = await getFacebookFlowState(pipelineId);
    return NextResponse.json(state);
  } catch (err: unknown) {
    const status = err instanceof FacebookApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không tải được flow-state.";
    return NextResponse.json({ error: message }, { status });
  }
}
