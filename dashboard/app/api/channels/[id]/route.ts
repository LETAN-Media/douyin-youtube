import { NextResponse } from "next/server";
import { getChannelDetail } from "@/lib/api";

export async function GET(
  _request: Request,
  props: { params: Promise<{ id: string }> },
) {
  const { id } = await props.params;
  try {
    const data = await getChannelDetail(id);
    return NextResponse.json(data);
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : "Failed to get channel detail";
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
