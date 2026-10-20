import { NextResponse } from "next/server";
import { getFacebookScheduleStatus } from "@/lib/facebook-api";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ pipelineId: string }> },
) {
  try {
    const { pipelineId } = await params;
    const status = await getFacebookScheduleStatus(pipelineId);
    return NextResponse.json(status);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Failed to get scheduler status";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
