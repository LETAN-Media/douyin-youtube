import { NextResponse } from "next/server";
import { FacebookApiError, deleteManualDestination } from "@/lib/facebook-api";

// Server-side proxy: browser calls same-origin
// DELETE /api/facebook/manual/destinations/{id}
// which lands on backend DELETE /api/facebook/youtube-destinations/{id}.
// Token (FACEBOOK_ADMIN_TOKEN) never leaves the server.
export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ destinationId: string }> },
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
