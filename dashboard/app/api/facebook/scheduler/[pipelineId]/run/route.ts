import { NextRequest, NextResponse } from "next/server";
import { scheduleToday } from "@/lib/facebook-api";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ pipelineId: string }> }
) {
  try {
    const { pipelineId } = await params;
    const body = await request.json();
    const { destinationId } = body;

    if (!destinationId) {
      return NextResponse.json({ error: "destinationId is required" }, { status: 400 });
    }

    const result = await scheduleToday(pipelineId, destinationId);
    return NextResponse.json(result);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Failed to run batch";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}