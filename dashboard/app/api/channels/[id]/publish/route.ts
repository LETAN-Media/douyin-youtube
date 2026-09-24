import { NextResponse } from "next/server";
import { getServerEnv } from "@/lib/env";

// Proxy: POST /api/channels/:id/publish -> FastAPI
// POST /api/channels/{destination_id}/publish (channel_workspace_publish_endpoint).
// This route was missing, so the channel workspace "Publish Now" button got a
// 404 HTML page and `await res.json()` threw on Safari as:
// "The string did not match the expected pattern."
// Pass the backend status/body through untouched so the client keeps its
// DUPLICATE_VIDEO handling (code + external_url).
export async function POST(
  request: Request,
  props: { params: Promise<{ id: string }> },
) {
  const { id } = await props.params;
  try {
    const body = await request.json();
    const { apiUrl, adminToken } = getServerEnv();
    if (!apiUrl) {
      return NextResponse.json(
        { error: "DOUYIN_API_URL chưa được cấu hình." },
        { status: 500 },
      );
    }
    if (!adminToken) {
      return NextResponse.json(
        { error: "DOUYIN_ADMIN_TOKEN chưa được cấu hình." },
        { status: 500 },
      );
    }

    const res = await fetch(
      `${apiUrl}/api/channels/${encodeURIComponent(id)}/publish`,
      {
        method: "POST",
        headers: {
          "X-Admin-Token": adminToken,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
        cache: "no-store",
      },
    );

    const text = await res.text();
    let data: unknown = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = { detail: text.slice(0, 500) };
      }
    }
    return NextResponse.json(data, { status: res.status });
  } catch (err: unknown) {
    const message =
      err instanceof Error ? err.message : "Đăng video thất bại.";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
