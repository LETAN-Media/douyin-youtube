import { NextResponse } from "next/server";
import { FacebookApiError, createFacebookSource } from "@/lib/facebook-api";

// Server-side proxy: browser calls same-origin
// POST /api/facebook/pipelines/{pipelineId}/sources
// Token (FACEBOOK_ADMIN_TOKEN) never leaves the server.
export async function POST(
  request: Request,
  { params }: { params: Promise<{ pipelineId: string }> },
) {
  try {
    const { pipelineId } = await params;
    if (!pipelineId) {
      return NextResponse.json(
        { error: "Thiếu pipelineId.", message: "Thiếu pipelineId." },
        { status: 400 },
      );
    }
    const body = (await request.json().catch(() => null)) as {
      url?: unknown;
      page_name?: unknown;
    } | null;
    if (!body || typeof body.url !== "string" || !body.url.trim()) {
      return NextResponse.json(
        { error: "Thiếu Facebook URL.", message: "Thiếu Facebook URL." },
        { status: 400 },
      );
    }
    const created = await createFacebookSource(pipelineId, {
      url: body.url.trim(),
      page_name: typeof body.page_name === "string" && body.page_name.trim()
        ? body.page_name.trim()
        : undefined,
    });
    return NextResponse.json(created, { status: 201 });
  } catch (err: unknown) {
    const status = err instanceof FacebookApiError ? err.status : 500;
    const message =
      err instanceof Error ? err.message : "Không thêm được nguồn.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
