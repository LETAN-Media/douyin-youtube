import { createHmac, timingSafeEqual } from "crypto";
import { cookies } from "next/headers";
import { getServerEnv } from "./env";

export const SESSION_COOKIE = "dy_session";
const SESSION_TTL_SECONDS = 7 * 24 * 60 * 60;

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
