import { NextResponse } from "next/server";
import { DramaApiError, createDramaTemplate, listDramaTemplates } from "@/lib/drama-api";

export async function GET() {
  try {
    return NextResponse.json(await listDramaTemplates());
  } catch (err: unknown) {
    const status = err instanceof DramaApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không tải được templates.";
    return NextResponse.json({ error: message, message }, { status });
  }
}

export async function POST(request: Request) {
  try {
    const body = (await request.json().catch(() => null)) as Record<string, unknown> | null;
    if (!body || typeof body.name !== "string" || typeof body.asset_url !== "string") {
      return NextResponse.json({ error: "Thiếu name/asset_url." }, { status: 400 });
    }
    const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : undefined);
    return NextResponse.json(
      await createDramaTemplate({
        name: body.name,
        asset_url: body.asset_url,
        canvas_width: num(body.canvas_width),
        canvas_height: num(body.canvas_height),
        content_x: num(body.content_x),
        content_y: num(body.content_y),
        content_width: num(body.content_width),
        content_height: num(body.content_height),
      }),
      { status: 201 },
    );
  } catch (err: unknown) {
    const status = err instanceof DramaApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không tạo được template.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
