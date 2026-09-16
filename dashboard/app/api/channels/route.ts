import { NextResponse } from "next/server";
import { listChannels } from "@/lib/api";

export async function GET() {
  try {
    const data = await listChannels();
    return NextResponse.json(data);
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : "Failed to list channels";
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
