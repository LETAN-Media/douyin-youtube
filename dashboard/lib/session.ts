import { createHmac, timingSafeEqual } from "crypto";
import { cookies } from "next/headers";
import { getServerEnv } from "./env";

export const SESSION_COOKIE = "dy_session";
const SESSION_TTL_SECONDS = 7 * 24 * 60 * 60;

// Multi-user session (Phase 13): httpOnly cookie holding the backend opaque
// session token, HMAC-signed with DASHBOARD_SECRET so middleware/proxy can
// trust it without a backend roundtrip. The raw backend token never reaches
// browser JS (httpOnly) and is forwarded server-side as X-Session-Token.
export const USER_SESSION_COOKIE = "dy_user";
const USER_SESSION_TTL_SECONDS = 30 * 24 * 60 * 60;

export interface UserSessionData {
  uid: string;
  email: string;
  exp: number;
  token: string;
}

function b64urlEncode(input: string): string {
  return Buffer.from(input, "utf8")
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

function b64urlDecode(input: string): string {
  let s = input.replace(/-/g, "+").replace(/_/g, "/");
  while (s.length % 4 !== 0) s += "=";
  return Buffer.from(s, "base64").toString("utf8");
}

function sign(payload: string, secret: string): string {
  return createHmac("sha256", secret).update(payload).digest("hex");
}

export async function createSession(): Promise<string> {
  const { dashboardSecret } = getServerEnv();
  const exp = Math.floor(Date.now() / 1000) + SESSION_TTL_SECONDS;
  const payload = `admin:${exp}`;
  const sig = sign(payload, dashboardSecret);
  return `${exp}.${sig}`;
}

export async function verifySessionToken(
  token: string | undefined,
): Promise<boolean> {
  if (!token) return false;
  const { dashboardSecret } = getServerEnv();
  if (!dashboardSecret) return false;
  const [expRaw, sig] = token.split(".");
  if (!expRaw || !sig) return false;
  const exp = Number(expRaw);
  if (!Number.isFinite(exp) || exp < Math.floor(Date.now() / 1000)) return false;
  const expected = sign(`admin:${exp}`, dashboardSecret);
  if (sig.length !== expected.length) return false;
  try {
    return timingSafeEqual(Buffer.from(sig), Buffer.from(expected));
  } catch {
    return false;
  }
}

export async function isAuthenticated(): Promise<boolean> {
  const store = await cookies();
  return verifySessionToken(store.get(SESSION_COOKIE)?.value);
}

export function verifyPassword(input: string): boolean {
  const { dashboardSecret } = getServerEnv();
  if (!dashboardSecret || !input) return false;
  const a = Buffer.from(input);
  const b = Buffer.from(dashboardSecret);
  if (a.length !== b.length) {
    // Constant-time-ish compare against same-length buffer to avoid early exit.
    const pad = Buffer.alloc(Math.max(a.length, b.length));
    a.copy(pad);
    return (
      timingSafeEqual(pad, Buffer.concat([b, Buffer.alloc(pad.length - b.length)])) &&
      false
    );
  }
  return timingSafeEqual(a, b);
}

export function sessionCookieOptions(maxAge = SESSION_TTL_SECONDS) {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/",
    maxAge,
  };
}

export async function createUserSession(
  uid: string,
  email: string,
  backendToken: string,
  ttlSeconds = USER_SESSION_TTL_SECONDS,
): Promise<string> {
  const { dashboardSecret } = getServerEnv();
  const exp = Math.floor(Date.now() / 1000) + ttlSeconds;
  const payload = b64urlEncode(
    JSON.stringify({ uid, email, exp, token: backendToken }),
  );
  const sig = sign(payload, dashboardSecret);
  return `${payload}.${sig}`;
}

export async function verifyUserSessionToken(
  token: string | undefined,
): Promise<UserSessionData | null> {
  try {
    if (!token) return null;
    const { dashboardSecret } = getServerEnv();
    if (!dashboardSecret) return null;
    const dot = token.lastIndexOf(".");
    if (dot <= 0) return null;
    const payload = token.slice(0, dot);
    const sig = token.slice(dot + 1);
    const expected = sign(payload, dashboardSecret);
    if (sig.length !== expected.length) return null;
    if (!timingSafeEqual(Buffer.from(sig), Buffer.from(expected))) return null;
    const data = JSON.parse(b64urlDecode(payload)) as UserSessionData;
    if (!data.uid || !data.token) return null;
    if (
      !Number.isFinite(data.exp) ||
      data.exp < Math.floor(Date.now() / 1000)
    )
      return null;
    return data;
  } catch {
    return null;
  }
}

export async function getUserSession(): Promise<UserSessionData | null> {
  const store = await cookies();
  return verifyUserSessionToken(store.get(USER_SESSION_COOKIE)?.value);
}

export function userSessionCookieOptions(maxAge = USER_SESSION_TTL_SECONDS) {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/",
    maxAge,
  };
}
