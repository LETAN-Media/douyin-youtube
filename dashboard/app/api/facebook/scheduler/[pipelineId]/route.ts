import { NextRequest, NextResponse } from "next/server";
import { getFacebookSchedule, updateFacebookSchedule } from "@/lib/facebook-api";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ pipelineId: string }> }
) {
  try {
    const { pipelineId } = await params;
    const schedule = await getFacebookSchedule(pipelineId);
    return NextResponse.json(schedule);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Failed to get schedule";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ pipelineId: string }> }
) {
  try {
    const { pipelineId } = await params;
    const body = await request.json();
    const updated = await updateFacebookSchedule(pipelineId, body);
    return NextResponse.json(updated);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Failed to update schedule";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}