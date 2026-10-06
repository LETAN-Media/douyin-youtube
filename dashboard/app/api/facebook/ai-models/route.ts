import { NextResponse } from "next/server";
import { FacebookApiError, listAiModels } from "@/lib/facebook-api";

export async function GET() {
  try {
    return NextResponse.json(await listAiModels());
  } catch (err: unknown) {
    const status = err instanceof FacebookApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không tải được danh sách model.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
