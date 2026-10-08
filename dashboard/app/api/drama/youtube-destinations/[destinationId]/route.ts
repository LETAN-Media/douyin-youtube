import { NextResponse } from "next/server";
import { DramaApiError, disconnectDramaDestination } from "@/lib/drama-api";

export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ destinationId: string }> },
) {
  try {
    const { destinationId } = await params;
    if (!destinationId) {
      return NextResponse.json({ error: "Thiếu destinationId." }, { status: 400 });
    }
    return NextResponse.json(await disconnectDramaDestination(destinationId));
  } catch (err: unknown) {
    const status = err instanceof DramaApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không ngắt kết nối được.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
