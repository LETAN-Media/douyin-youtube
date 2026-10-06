import { NextResponse } from "next/server";
import { FacebookApiError, bulkDeleteManualPublications } from "@/lib/facebook-api";

export async function POST(request: Request) {
  try {
    const body = (await request.json().catch(() => null)) as { ids?: unknown } | null;
    const ids = Array.isArray(body?.ids)
      ? body.ids.filter((x): x is string => typeof x === "string").slice(0, 100)
      : [];
    return NextResponse.json(await bulkDeleteManualPublications(ids));
  } catch (err: unknown) {
    const status = err instanceof FacebookApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không xoá được.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
