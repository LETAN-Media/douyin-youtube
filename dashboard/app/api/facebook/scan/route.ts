import { NextResponse } from "next/server";
import { FacebookApiError, triggerFacebookScan } from "@/lib/facebook-api";

// Triggers a backend scan for a source. Token stays server-side.
export async function POST(request: Request) {
  try {
    const body = (await request.json()) as { sourceId?: string };
    if (!body.sourceId) {
      return NextResponse.json({ error: "Thiếu sourceId." }, { status: 400 });
    }
    const data = await triggerFacebookScan(body.sourceId);
    return NextResponse.json(data, { status: 202 });
  } catch (err: unknown) {
    const status = err instanceof FacebookApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không bắt đầu được scan.";
    return NextResponse.json({ error: message }, { status });
  }
}
