import { NextResponse } from "next/server";
import { FacebookApiError, listFacebookInventory } from "@/lib/facebook-api";

// Paginated inventory for client-side paging. Token stays server-side.
export async function GET(request: Request) {
  try {
    const url = new URL(request.url);
    const pipelineId = url.searchParams.get("pipelineId") ?? "";
    const limit = Number(url.searchParams.get("limit") ?? "50");
    const offset = Number(url.searchParams.get("offset") ?? "0");
    const status = url.searchParams.get("status") ?? undefined;
    if (!pipelineId) {
      return NextResponse.json({ error: "Thiếu pipelineId." }, { status: 400 });
    }
    const data = await listFacebookInventory(pipelineId, { limit, offset, status });
    return NextResponse.json(data);
  } catch (err: unknown) {
    const status = err instanceof FacebookApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không tải được inventory.";
    return NextResponse.json({ error: message }, { status });
  }
}
