import { NextResponse } from "next/server";
import { createSession, verifyPassword, sessionCookieOptions } from "@/lib/session";
import { SESSION_COOKIE } from "@/lib/session";

// JSON API (no server redirect): the browser navigates relatively,
// so login works behind any proxy/domain (Render, custom domain).
export async function POST(request: Request) {
  const form = await request.formData().catch(() => null);
  const password = form ? String(form.get("password") ?? "") : "";

  if (!verifyPassword(password)) {
    return NextResponse.json({ ok: false, error: "Mật khẩu không đúng." }, { status: 401 });
  }

  const token = await createSession();
  const res = NextResponse.json({ ok: true });
  res.cookies.set(SESSION_COOKIE, token, sessionCookieOptions());
  return res;
}
