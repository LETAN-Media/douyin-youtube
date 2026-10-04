import { NextResponse } from "next/server";

// TEMPORARY debug endpoint: reports ONLY booleans + HTTP statuses.
// Never returns values, prefixes, suffixes, or dumps. Behind dashboard auth
// via middleware. Remove after the Vercel env issue is resolved.
export async function GET() {
  const apiUrl = (process.env.FACEBOOK_API_URL ?? "").trim().replace(/\/+$/, "");
  const adminToken = (process.env.FACEBOOK_ADMIN_TOKEN ?? "").trim();

  let backendReachable = false;
  let authStatus: number | null = null;
  if (apiUrl && adminToken) {
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 15000);
      try {
        const res = await fetch(`${apiUrl}/api/facebook/pipelines`, {
          headers: { "X-Admin-Token": adminToken },
          cache: "no-store",
          signal: controller.signal,
        });
        backendReachable = true;
        authStatus = res.status;
      } finally {
        clearTimeout(timer);
      }
    } catch {
      backendReachable = false;
    }
  }

  return NextResponse.json({
    FACEBOOK_API_URL: apiUrl.length > 0,
    FACEBOOK_ADMIN_TOKEN: adminToken.length > 0,
    VERCEL_ENV: process.env.VERCEL_ENV ?? "unknown",
    backend_reachable: backendReachable,
    auth_status: authStatus,
  });
}
