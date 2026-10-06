import { NextResponse } from "next/server";
import { FacebookApiError, deleteManualPublication, getManualPublication } from "@/lib/facebook-api";

export async function GET(
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
    return NextResponse.json(await getManualPublication(id));
  } catch (err: unknown) {
    const status = err instanceof FacebookApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không tải được bản đăng.";
    return NextResponse.json({ error: message, message }, { status });
  }
}

export async function DELETE(
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
    return NextResponse.json(await deleteManualPublication(id));
  } catch (err: unknown) {
    const status = err instanceof FacebookApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không xoá được bản đăng.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
