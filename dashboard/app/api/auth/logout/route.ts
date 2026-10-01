import { NextResponse } from "next/server";
import { SESSION_COOKIE, USER_SESSION_COOKIE } from "@/lib/session";
import { currentBackendToken } from "@/lib/forward";
import { getServerEnv } from "@/lib/env";

// JSON API (no server redirect): the browser navigates relatively.
// Revokes the backend session best-effort, then clears both cookies.
export async function POST() {
  const token = await currentBackendToken().catch(() => null);
  if (token) {
    try {
      const { apiUrl } = getServerEnv();
      if (apiUrl) {
        await fetch(`${apiUrl}/api/auth/logout`, {
          method: "POST",
          headers: { "X-Session-Token": token },
          cache: "no-store",
        });
      }
    } catch {
      // Logout is local-first; a backend failure must not trap the user.
    }
  }
  const clear = {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/",
    maxAge: 0,
  };
  const res = NextResponse.json({ ok: true });
  res.cookies.set(SESSION_COOKIE, "", clear);
  res.cookies.set(USER_SESSION_COOKIE, "", clear);
  return res;
}
