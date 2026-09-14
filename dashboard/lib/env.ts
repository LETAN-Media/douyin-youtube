// Server-side environment. Never import from client components.
// No NEXT_PUBLIC_* secrets are used anywhere in this app.

export function getServerEnv() {
  const apiUrl = (process.env.DOUYIN_API_URL ?? "").trim().replace(/\/+$/, "");
  const adminToken = (process.env.DOUYIN_ADMIN_TOKEN ?? "").trim();
  const dashboardSecret = (process.env.DASHBOARD_SECRET ?? "").trim();

  return { apiUrl, adminToken, dashboardSecret };
}

export function assertServerEnv() {
  const env = getServerEnv();
  const missing: string[] = [];
  if (!env.apiUrl) missing.push("DOUYIN_API_URL");
  if (!env.adminToken) missing.push("DOUYIN_ADMIN_TOKEN");
  if (!env.dashboardSecret) missing.push("DASHBOARD_SECRET");
  if (missing.length > 0) {
    throw new Error(`Missing server env: ${missing.join(", ")}`);
  }
  return env;
}
