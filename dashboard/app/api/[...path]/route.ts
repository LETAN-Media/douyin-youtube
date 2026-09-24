import { NextResponse } from "next/server";
import { getServerEnv } from "@/lib/env";

// Generic backend forwarder for dashboard API calls.
//
// Several workspace features (sources CRUD, cookie management, auto status,
// …) previously had NO matching Next.js route, so the browser got a 404 HTML
// page and `await res.json()` threw on Safari as:
// "The string did not match the expected pattern."
// This catch-all forwards any /api/... request to the FastAPI backend and
// passes status/body through untouched (JSON stays JSON).
// Specific routes (e.g. /api/manual/publish) still take precedence.
async function forward(request: Request, path: string[]) {
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

  const incoming = new URL(request.url);
  const target =
    `${apiUrl}/api/${path.map((s) => encodeURIComponent(s)).join("/")}` +
    (incoming.search || "");

  const headers: Record<string, string> = { "X-Admin-Token": adminToken };
  const contentType = request.headers.get("content-type");
  if (contentType) headers["Content-Type"] = contentType;

  let body: string | undefined;
  if (request.method !== "GET" && request.method !== "HEAD") {
    try {
      body = await request.text();
    } catch {
      body = undefined;
    }
  }

  try {
    const res = await fetch(target, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
    });
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
      err instanceof Error ? err.message : "Không kết nối được backend.";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}

export async function GET(
  request: Request,
  props: { params: Promise<{ path: string[] }> },
) {
  const { path } = await props.params;
  return forward(request, path);
}

export async function POST(
  request: Request,
  props: { params: Promise<{ path: string[] }> },
) {
  const { path } = await props.params;
  return forward(request, path);
}

export async function PATCH(
  request: Request,
  props: { params: Promise<{ path: string[] }> },
) {
  const { path } = await props.params;
  return forward(request, path);
}

export async function PUT(
  request: Request,
  props: { params: Promise<{ path: string[] }> },
) {
  const { path } = await props.params;
  return forward(request, path);
}

export async function DELETE(
  request: Request,
  props: { params: Promise<{ path: string[] }> },
) {
  const { path } = await props.params;
  return forward(request, path);
}
