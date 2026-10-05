import { NextResponse } from "next/server";
import {
  FacebookApiError,
  createFacebookYoutubeDestination,
  listFacebookDestinations,
} from "@/lib/facebook-api";

// Server-side proxy: browser calls same-origin
// /api/facebook/pipelines/{pipelineId}/youtube-destinations
// Token (FACEBOOK_ADMIN_TOKEN) never leaves the server.
export async function GET(
  _request: Request,
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
    const list = await listFacebookDestinations(pipelineId);
    return NextResponse.json(list);
  } catch (err: unknown) {
    const status = err instanceof FacebookApiError ? err.status : 500;
    const message =
      err instanceof Error ? err.message : "Không tải được danh sách kênh YouTube.";
    return NextResponse.json({ error: message, message }, { status });
  }
}

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
    let visibility = "public";
    let enabled = true;
    try {
      const body = (await request.json()) as {
        visibility?: unknown;
        enabled?: unknown;
      };
      if (typeof body.visibility === "string" && body.visibility.trim()) {
        visibility = body.visibility.trim();
      }
      if (typeof body.enabled === "boolean") {
        enabled = body.enabled;
      }
    } catch {
      // empty / invalid JSON body -> fall back to defaults
    }
    const created = await createFacebookYoutubeDestination(pipelineId, {
      visibility,
      enabled,
    });
    return NextResponse.json(created, { status: 201 });
  } catch (err: unknown) {
    const status = err instanceof FacebookApiError ? err.status : 500;
    const message =
      err instanceof Error ? err.message : "Không thể tạo kênh đích.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
