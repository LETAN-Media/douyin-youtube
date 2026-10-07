import { NextRequest, NextResponse } from "next/server";

const BASE_URL = (process.env.DRAMA_API_URL ?? "").trim().replace(/\/+$/, "");
const ADMIN_TOKEN = (process.env.DRAMA_ADMIN_TOKEN ?? "").trim();

function proxy(path: string, init: RequestInit = {}) {
  if (!BASE_URL) return NextResponse.json({ error: "DRAMA_API_URL not configured" }, { status: 500 });
  if (!ADMIN_TOKEN) return NextResponse.json({ error: "DRAMA_ADMIN_TOKEN not configured" }, { status: 500 });
  const url = `${BASE_URL}${path}`;
  return fetch(url, {
    ...init,
    headers: {
      "X-Admin-Token": ADMIN_TOKEN,
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
    cache: "no-store",
  });
}

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ seriesId: string }> }
) {
  const { seriesId } = await params;
  const { searchParams } = new URL(req.url);
  const limit = searchParams.get("limit") || "500";
  const offset = searchParams.get("offset") || "0";
  const status = searchParams.get("status") || "";
  const query = new URLSearchParams({ limit, offset });
  if (status) query.set("status", status);
  const res = await proxy(`/api/drama/series/${encodeURIComponent(seriesId)}/episodes?${query.toString()}`);
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}