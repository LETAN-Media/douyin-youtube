import { NextResponse } from "next/server";
import {
  FacebookApiError,
  deleteFacebookSource,
  updateFacebookSource,
} from "@/lib/facebook-api";

async function getId(params: Promise<{ sourceId: string }>) {
  const { sourceId } = await params;
  return sourceId;
}

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ sourceId: string }> },
) {
  try {
    const sourceId = await getId(params);
    if (!sourceId) {
      return NextResponse.json(
        { error: "Thiếu sourceId.", message: "Thiếu sourceId." },
        { status: 400 },
      );
    }
    const body = (await request.json().catch(() => null)) as { enabled?: unknown } | null;
    if (!body || typeof body.enabled !== "boolean") {
      return NextResponse.json(
        { error: "Thiếu enabled.", message: "Thiếu enabled." },
        { status: 400 },
      );
    }
    return NextResponse.json(await updateFacebookSource(sourceId, { enabled: body.enabled }));
  } catch (err: unknown) {
    const status = err instanceof FacebookApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không cập nhật được nguồn.";
    return NextResponse.json({ error: message, message }, { status });
  }
}

export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ sourceId: string }> },
) {
  try {
    const sourceId = await getId(params);
    if (!sourceId) {
      return NextResponse.json(
        { error: "Thiếu sourceId.", message: "Thiếu sourceId." },
        { status: 400 },
      );
    }
    return NextResponse.json(await deleteFacebookSource(sourceId));
  } catch (err: unknown) {
    const status = err instanceof FacebookApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không xoá được nguồn.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
