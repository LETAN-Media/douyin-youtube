import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const BACKEND_ENV = "YOUTUBE_FB_API_URL";
const ADMIN_TOKEN_ENV = "YOUTUBE_FB_ADMIN_TOKEN";

function getBackend(): { base: string; token: string } {
  const base = (process.env[BACKEND_ENV] ?? "").trim().replace(/\/+$/, "");
  if (!base) throw new Error("YOUTUBE_FB_API_URL chưa được cấu hình.");
  const token = (process.env[ADMIN_TOKEN_ENV] ?? "").trim();
  if (!token || token === "CHANGE_ME_LONG_RANDOM_TOKEN")
    throw new Error("YOUTUBE_FB_ADMIN_TOKEN chưa được cấu hình.");
  return { base, token };
}

async function forward(method: string, url: URL, search: string, body?: unknown): Promise<NextResponse> {
  const { base, token } = getBackend();
  const target = `${base}${url.pathname}${search}`;
  const headers: Record<string, string> = {
    "X-Admin-Token": token,
    Accept: "application/json",
  };
  const init: RequestInit = { method, headers, cache: "no-store" };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 35000);
  try {
    const res = await fetch(target, { ...init, signal: controller.signal });
    const text = await res.text().catch(() => "");
    if (!text) return new NextResponse(null, { status: res.status });
    let data: unknown;
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
    return NextResponse.json(data, {
      status: res.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (err: any) {
    if (err?.name === "AbortError") {
      return NextResponse.json({ error: "TIMEOUT", message: "Backend timeout." }, { status: 504 });
    }
    return NextResponse.json({ error: "PROXY_ERROR", message: err?.message || "Proxy error" }, { status: 502 });
  } finally {
    clearTimeout(timer);
  }
}

export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  const slug = url.pathname.split("/").slice(4); // /api/youtube-fb/:...
  const path = `/api/youtube-fb/${slug.join("/")}`;
  return forward("GET", new URL(path, "http://placeholder"), url.search, undefined);
}

export async function POST(req: NextRequest) {
  const url = new URL(req.url);
  const slug = url.pathname.split("/").slice(4);
  const path = `/api/youtube-fb/${slug.join("/")}`;
  let body: unknown = undefined;
  try {
    body = await req.json();
  } catch {
    body = undefined;
  }
  return forward("POST", new URL(path, "http://placeholder"), url.search, body);
}

export async function PATCH(req: NextRequest) {
  const url = new URL(req.url);
  const slug = url.pathname.split("/").slice(4);
  const path = `/api/youtube-fb/${slug.join("/")}`;
  const body = await req.json().catch(() => undefined);
  return forward("PATCH", new URL(path, "http://placeholder"), url.search, body);
}

export async function DELETE(req: NextRequest) {
  const url = new URL(req.url);
  const slug = url.pathname.split("/").slice(4);
  const path = `/api/youtube-fb/${slug.join("/")}`;
  return forward("DELETE", new URL(path, "http://placeholder"), url.search, undefined);
}

export async function PUT(req: NextRequest) {
  const url = new URL(req.url);
  const slug = url.pathname.split("/").slice(4);
  const path = `/api/youtube-fb/${slug.join("/")}`;
  const body = await req.json().catch(() => undefined);
  return forward("PUT", new URL(path, "http://placeholder"), url.search, body);
}
