import { NextResponse } from "next/server";
import { FacebookApiError, retryManualPublication } from "@/lib/facebook-api";

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { id } = await params;
    if (!id) {
      return NextResponse.json(
        { error: "Thiếu id.", message: "Thiếu id." },
        { status: 400 },
      );
    }
    return NextResponse.json(await retryManualPublication(id));
  } catch (err: unknown) {
    const status = err instanceof FacebookApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không retry được.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
