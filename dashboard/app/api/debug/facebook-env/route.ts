import { NextResponse } from "next/server";

// TEMPORARY debug endpoint: reports ONLY booleans about Facebook env wiring.
// Never returns values, prefixes, suffixes, or dumps. Behind dashboard auth
// via middleware. Remove after the Vercel env issue is resolved.
export async function GET() {
  const apiUrl = (process.env.FACEBOOK_API_URL ?? "").trim();
  const adminToken = (process.env.FACEBOOK_ADMIN_TOKEN ?? "").trim();
  return NextResponse.json({
    FACEBOOK_API_URL: apiUrl.length > 0,
    FACEBOOK_ADMIN_TOKEN: adminToken.length > 0,
    VERCEL_ENV: process.env.VERCEL_ENV ?? "unknown",
  });
}
