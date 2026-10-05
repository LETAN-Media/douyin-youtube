import { NextResponse } from "next/server";
import { FacebookApiError, startFacebookOAuth } from "@/lib/facebook-api";

// Starts a YouTube OAuth flow for a destination and returns the Google
// authorization URL. Token stays server-side; browser redirects to Google.
export async function POST(request: Request) {
  try {
    const body = (await request.json()) as { destinationId?: string; return_to?: string };
    if (!body.destinationId) {
      return NextResponse.json({ error: "Thiếu destinationId." }, { status: 400 });
    }
    const data = await startFacebookOAuth(
      body.destinationId,
      typeof body.return_to === "string" ? body.return_to : undefined,
    );
    return NextResponse.json(data);
  } catch (err: unknown) {
    const status = err instanceof FacebookApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không bắt đầu được OAuth.";
    return NextResponse.json({ error: message }, { status });
  }
}
