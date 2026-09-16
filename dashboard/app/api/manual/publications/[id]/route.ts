import { NextResponse } from "next/server";
import { getManualPublication } from "@/lib/api";

export async function GET(
  _request: Request,
  props: { params: Promise<{ id: string }> },
) {
  try {
    const params = await props.params;
    const item = await getManualPublication(params.id);
    return NextResponse.json(item);
  } catch (err: unknown) {
    const status = (err as { status?: number })?.status || 500;
    const message = err instanceof Error ? err.message : "Không tìm thấy publication.";
    return NextResponse.json({ error: message }, { status });
  }
}
