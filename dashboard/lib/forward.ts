// Backend identity forwarding (Phase 18).
//
// Regular user requests are forwarded with THEIR OWN session identity
// (X-Session-Token) so the backend enforces tenant isolation. They are
// NEVER escalated to the admin token server-side. Only the legacy admin
// cookie (dy_session) forwards X-Admin-Token.

import { cookies } from "next/headers";
import { getServerEnv } from "./env";
import {
  USER_SESSION_COOKIE,
  SESSION_COOKIE,
  verifySessionToken,
  verifyUserSessionToken,
} from "./session";

export interface ForwardAuth {
  headers: Record<string, string>;
  kind: "user" | "admin" | "none";
}

/** Resolve backend auth headers for the current incoming request. */
export async function forwardAuthHeaders(): Promise<ForwardAuth> {
  const store = await cookies();

  // 1. Regular user session wins when present and valid.
  const user = await verifyUserSessionToken(
    store.get(USER_SESSION_COOKIE)?.value,
  );
  if (user) {
    return { headers: { "X-Session-Token": user.token }, kind: "user" };
  }

  // 2. Legacy admin session falls back to the admin token.
  const legacy = store.get(SESSION_COOKIE)?.value;
  if (await verifySessionToken(legacy)) {
    const { adminToken } = getServerEnv();
    if (adminToken) {
      return { headers: { "X-Admin-Token": adminToken }, kind: "admin" };
    }
  }

  return { headers: {}, kind: "none" };
}

/** Backend session token for explicit logout revocation (if any). */
export async function currentBackendToken(): Promise<string | null> {
  const store = await cookies();
  const user = await verifyUserSessionToken(
    store.get(USER_SESSION_COOKIE)?.value,
  );
  return user?.token ?? null;
}
