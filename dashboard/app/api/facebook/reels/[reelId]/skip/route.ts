import { NextResponse } from "next/server";
import { FacebookApiError, skipFacebookReel } from "@/lib/facebook-api";

export async function POST(
  _request: Request,
  props: { params: Promise<{ reelId: string }> },
) {
  try {
    const { reelId } = await props.params;
    const data = await skipFacebookReel(reelId);
    return NextResponse.json(data);
  } catch (err: unknown) {
    const status = err instanceof FacebookApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Skip thất bại.";
    return NextResponse.json({ error: message }, { status });
  }
}
