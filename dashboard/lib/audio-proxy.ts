import { NextResponse } from "next/server";

const BASE = (process.env.AUDIO_API_URL ?? "")
  .trim()
  .replace(/\/+$/, "")
  .replace(/\/api\/audio$/, "");
const TOKEN = (process.env.AUDIO_API_TOKEN ?? "").trim();

export async function proxyAudio(
  path: string,
  init: RequestInit = {},
  timeoutMs = 30000,
): Promise<NextResponse> {
  if (!BASE || !TOKEN) {
    return NextResponse.json(
      { error: "AUDIO_API_URL / AUDIO_API_TOKEN chưa được cấu hình." },
      { status: 500 },
    );
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const headers = new Headers(init.headers);
    headers.set("X-Admin-Token", TOKEN);
    const res = await fetch(`${BASE}${path}`, {
      ...init, headers, cache: "no-store", signal: controller.signal,
    });
    const text = await res.text();
    let data: unknown = text;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      // keep raw
    }
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json(
      { error: "Không kết nối được audio backend." }, { status: 503 });
  } finally {
    clearTimeout(timer);
  }
}
