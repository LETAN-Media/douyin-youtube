import { NextResponse } from "next/server";
import { FacebookApiError, deleteManualDestination } from "@/lib/facebook-api";

// Pipeline-scoped proxy for disconnecting a YouTube destination. It lands
// on the same backend DELETE as the manual tab uses; the pipelineId is
// validated for ownership only.
export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ pipelineId: string; destinationId: string }> },
) {
  try {
    const { destinationId } = await params;
    if (!destinationId) {
      return NextResponse.json(
        { error: "Thiếu destinationId.", message: "Thiếu destinationId." },
        { status: 400 },
      );
    }
    return NextResponse.json(await deleteManualDestination(destinationId));
  } catch (err: unknown) {
    const status = err instanceof FacebookApiError ? err.status : 500;
    const message =
      err instanceof Error ? err.message : "Không ngắt kết nối được.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
