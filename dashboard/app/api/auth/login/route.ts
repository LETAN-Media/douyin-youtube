import { NextResponse } from "next/server";
import {
  createSession,
  verifyPassword,
  sessionCookieOptions,
  createUserSession,
  userSessionCookieOptions,
  USER_SESSION_COOKIE,
  SESSION_COOKIE,
} from "@/lib/session";
import { getServerEnv } from "@/lib/env";

// JSON API (no server redirect): the browser navigates relatively,
// so login works behind any proxy/domain.
//
// Two login modes (admin flow is preserved until user auth is stable):
//  1. User login: form has `email` -> backend POST /api/auth/login.
//     Sets the httpOnly `dy_user` cookie (backend token, HMAC-signed).
//  2. Legacy admin login: form has only `password` -> DASHBOARD_SECRET.
//     Sets the legacy `dy_session` cookie.
export async function POST(request: Request) {
  const form = await request.formData().catch(() => null);
  const email = form ? String(form.get("email") ?? "").trim() : "";
  const password = form ? String(form.get("password") ?? "") : "";

  if (email) {
    // ---- User login via backend ----
    const { apiUrl } = getServerEnv();
    if (!apiUrl) {
      return NextResponse.json(
        { ok: false, error: "DOUYIN_API_URL chưa được cấu hình." },
        { status: 500 },
      );
    }
    try {
      const res = await fetch(`${apiUrl}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
        cache: "no-store",
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data?.token || !data?.user) {
        return NextResponse.json(
          { ok: false, error: "Email hoặc mật khẩu không đúng." },
          { status: 401 },
        );
      }
      const cookie = await createUserSession(
        String(data.user.id ?? ""),
        String(data.user.email ?? email),
        String(data.token),
      );
      const out = NextResponse.json({
        ok: true,
        user: data.user,
        workspaces: data.workspaces ?? [],
      });
      out.cookies.set(USER_SESSION_COOKIE, cookie, userSessionCookieOptions());
      // A login is exactly one identity: drop the other cookie.
      out.cookies.set(SESSION_COOKIE, "", {
        httpOnly: true,
        path: "/",
        maxAge: 0,
      });
      return out;
    } catch {
      return NextResponse.json(
        { ok: false, error: "Không kết nối được backend." },
        { status: 502 },
      );
    }
  }

  // ---- Legacy admin login (preserved) ----
  if (!verifyPassword(password)) {
    return NextResponse.json(
      { ok: false, error: "Mật khẩu không đúng." },
      { status: 401 },
    );
  }

  const token = await createSession();
  const res = NextResponse.json({ ok: true, admin: true });
  res.cookies.set(SESSION_COOKIE, token, sessionCookieOptions());
  res.cookies.set(USER_SESSION_COOKIE, "", {
    httpOnly: true,
    path: "/",
    maxAge: 0,
  });
  return res;
}
