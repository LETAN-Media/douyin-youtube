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

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (
    pathname.startsWith("/_next") ||
    pathname.startsWith("/favicon") ||
    pathname.startsWith("/api/auth/")
  ) {
    return NextResponse.next();
  }

  const secret = process.env.DASHBOARD_SECRET ?? "";
  const token = request.cookies.get("dy_session")?.value;
  const authenticated = await verifyToken(token, secret);

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
