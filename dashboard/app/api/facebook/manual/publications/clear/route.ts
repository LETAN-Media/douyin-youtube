import { NextResponse } from "next/server";
import { FacebookApiError, clearManualHistory } from "@/lib/facebook-api";

export async function POST(request: Request) {
  try {
    const body = (await request.json().catch(() => null)) as {
      destination_id?: unknown;
      only_failed?: unknown;
      confirm?: unknown;
    } | null;
    if (body?.confirm !== true) {
      return NextResponse.json(
        { error: "Cần xác nhận xoá.", message: "Cần xác nhận xoá." },
        { status: 400 },
      );
    }
    return NextResponse.json(
      await clearManualHistory({
        destination_id:
          typeof body.destination_id === "string" ? body.destination_id : undefined,
        only_failed: body.only_failed === true,
      }),
    );
  } catch (err: unknown) {
    const status = err instanceof FacebookApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không xoá được lịch sử.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
