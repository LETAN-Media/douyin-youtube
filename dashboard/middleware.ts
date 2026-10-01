import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Edge-compatible HMAC verification with Web Crypto (no node:crypto here).
function hexToBytes(hex: string): Uint8Array | null {
  if (hex.length % 2 !== 0 || !/^[0-9a-fA-F]+$/.test(hex)) return null;
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) {
    out[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  }
  return out;
}

async function verifyToken(
  token: string | undefined,
  secret: string,
): Promise<boolean> {
  try {
    if (!token || !secret) return false;
    const [expRaw, sigHex] = token.split(".");
    if (!expRaw || !sigHex) return false;
    const exp = Number(expRaw);
    if (!Number.isFinite(exp) || exp < Math.floor(Date.now() / 1000)) {
      return false;
    }
    const sig = hexToBytes(sigHex);
    if (!sig || sig.length !== 32) return false;
    const key = await crypto.subtle.importKey(
      "raw",
      new TextEncoder().encode(secret),
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["verify"],
    );
    return await crypto.subtle.verify(
      "HMAC",
      key,
      sig.buffer as ArrayBuffer,
      new TextEncoder().encode(`admin:${exp}`),
    );
  } catch {
    return false;
  }
}

// Multi-user session cookie: payload_b64.sig where payload is
// {uid,email,exp,token}. Verified with the same DASHBOARD_SECRET.
function b64urlDecode(input: string): string {
  let s = input.replace(/-/g, "+").replace(/_/g, "/");
  while (s.length % 4 !== 0) s += "=";
  try {
    return atob(s);
  } catch {
    return "";
  }
}

async function verifyUserToken(
  token: string | undefined,
  secret: string,
): Promise<boolean> {
  try {
    if (!token || !secret) return false;
    const dot = token.lastIndexOf(".");
    if (dot <= 0) return false;
    const payload = token.slice(0, dot);
    const sigHex = token.slice(dot + 1);
    const raw = b64urlDecode(payload);
    if (!raw) return false;
    const data = JSON.parse(raw) as {
      uid?: string;
      exp?: number;
      token?: string;
    };
    if (!data.uid || !data.token) return false;
    if (
      !Number.isFinite(data.exp) ||
      (data.exp as number) < Math.floor(Date.now() / 1000)
    ) {
      return false;
    }
    const sig = hexToBytes(sigHex);
    if (!sig || sig.length !== 32) return false;
    const key = await crypto.subtle.importKey(
      "raw",
      new TextEncoder().encode(secret),
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["verify"],
    );
    // Must match lib/session.ts createUserSession: HMAC(payload_b64).
    return await crypto.subtle.verify(
      "HMAC",
      key,
      sig.buffer as ArrayBuffer,
      new TextEncoder().encode(payload),
    );
  } catch {
    return false;
  }
}

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (
    pathname.startsWith("/_next") ||
    pathname.startsWith("/favicon") ||
    pathname.startsWith("/api/auth/")
  ) {
    return NextResponse.next();
  }

  // Public routes for Google OAuth verification (no login required):
  // legal pages are fully public; "/" renders a public landing page for
  // guests and the dashboard for authenticated users (decided in page.tsx).
  if (
    pathname === "/" ||
    pathname === "/privacy" ||
    pathname.startsWith("/privacy/") ||
    pathname === "/terms" ||
    pathname.startsWith("/terms/")
  ) {
    return NextResponse.next();
  }

  const secret = process.env.DASHBOARD_SECRET ?? "";
  // Either the legacy admin cookie OR a signed user session grants access.
  // (Tenant isolation itself is enforced by the backend per request.)
  const legacyToken = request.cookies.get("dy_session")?.value;
  const userToken = request.cookies.get("dy_user")?.value;
  const authenticated =
    (await verifyToken(legacyToken, secret)) ||
    (await verifyUserToken(userToken, secret));

  if (pathname === "/login") {
    if (authenticated) {
      const url = request.nextUrl.clone();
      url.pathname = "/";
      return NextResponse.redirect(url);
    }
    return NextResponse.next();
  }

  if (!secret || !authenticated) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
