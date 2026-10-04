import { NextResponse } from "next/server";
import { FacebookApiError, listFacebookPublications } from "@/lib/facebook-api";

// Paginated publications for client-side paging. Token stays server-side.
export async function GET(request: Request) {
  try {
    const url = new URL(request.url);
    const pipelineId = url.searchParams.get("pipelineId") ?? "";
    const limit = Number(url.searchParams.get("limit") ?? "100");
    const offset = Number(url.searchParams.get("offset") ?? "0");
    if (!pipelineId) {
      return NextResponse.json({ error: "Thiếu pipelineId." }, { status: 400 });
    }
    const data = await listFacebookPublications(pipelineId, { limit, offset });
    return NextResponse.json(data);
  } catch (err: unknown) {
    const status = err instanceof FacebookApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không tải được publications.";
    return NextResponse.json({ error: message }, { status });
  }
}
