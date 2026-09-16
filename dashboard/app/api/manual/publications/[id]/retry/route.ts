import { NextResponse } from "next/server";
import { retryManualPublication } from "@/lib/api";

export async function POST(
  _request: Request,
  props: { params: Promise<{ id: string }> },
) {
  try {
    const params = await props.params;
    const item = await retryManualPublication(params.id);
    return NextResponse.json(item);
  } catch (err: unknown) {
    const status = (err as { status?: number })?.status || 500;
    const message = err instanceof Error ? err.message : "Retry thất bại.";
    return NextResponse.json({ error: message }, { status });
  }
}
