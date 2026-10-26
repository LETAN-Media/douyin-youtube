import { NextResponse } from "next/server";
import {
  bulkExcludeTikTokReels,
  bulkRestoreTikTokReels,
  deleteTikTokReel,
  listTikTokInventory,
  restoreTikTokReel,
  TikTokApiError,
} from "@/lib/tiktok-api";

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const sourceId = searchParams.get("source_id");
    if (!sourceId) {
      return NextResponse.json({ error: "Thiếu source_id." }, { status: 400 });
    }
    const inventory = await listTikTokInventory(sourceId);
    return NextResponse.json(inventory);
  } catch (err: unknown) {
    const status = err instanceof TikTokApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không tải được inventory.";
    return NextResponse.json({ error: message, message }, { status });
  }
}

export async function DELETE(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const queryReelId = searchParams.get("reel_id");
    const queryPipelineId = searchParams.get("pipeline_id");

    let bodyReelId: string | undefined;
    let bodyReelIds: string[] | undefined;
    let bodyPipelineId: string | undefined;

    try {
      const body = await request.json();
      bodyReelId = body?.reel_id;
      bodyReelIds = body?.reel_ids;
      bodyPipelineId = body?.pipeline_id;
    } catch {
      // Body is optional if params in URL
    }

    const pipelineId = queryPipelineId || bodyPipelineId;

    if (bodyReelIds && Array.isArray(bodyReelIds) && bodyReelIds.length > 0) {
      if (!pipelineId) {
        return NextResponse.json({ error: "Thiếu pipeline_id để xóa nhiều video." }, { status: 400 });
      }
      const res = await bulkExcludeTikTokReels(pipelineId, bodyReelIds);
      return NextResponse.json(res);
    }

    const reelId = queryReelId || bodyReelId;
    if (!reelId) {
      return NextResponse.json({ error: "Thiếu reel_id để xóa video." }, { status: 400 });
    }

    const res = await deleteTikTokReel(reelId, pipelineId || undefined);
    return NextResponse.json(res);
  } catch (err: unknown) {
    const status = err instanceof TikTokApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Xóa video thất bại.";
    return NextResponse.json({ error: message, message }, { status });
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const action = body?.action || "exclude";
    const pipelineId = body?.pipeline_id;
    const reelId = body?.reel_id;
    const reelIds = body?.reel_ids;

    if (action === "restore") {
      if (Array.isArray(reelIds) && reelIds.length > 0) {
        if (!pipelineId) {
          return NextResponse.json({ error: "Thiếu pipeline_id." }, { status: 400 });
        }
        const res = await bulkRestoreTikTokReels(pipelineId, reelIds);
        return NextResponse.json(res);
      }
      if (!reelId) {
        return NextResponse.json({ error: "Thiếu reel_id để khôi phục." }, { status: 400 });
      }
      const res = await restoreTikTokReel(reelId, pipelineId);
      return NextResponse.json(res);
    } else {
      // action === "exclude"
      if (Array.isArray(reelIds) && reelIds.length > 0) {
        if (!pipelineId) {
          return NextResponse.json({ error: "Thiếu pipeline_id." }, { status: 400 });
        }
        const res = await bulkExcludeTikTokReels(pipelineId, reelIds);
        return NextResponse.json(res);
      }
      if (!reelId) {
        return NextResponse.json({ error: "Thiếu reel_id để loại trừ." }, { status: 400 });
      }
      const res = await deleteTikTokReel(reelId, pipelineId);
      return NextResponse.json(res);
    }
  } catch (err: unknown) {
    const status = err instanceof TikTokApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Thao tác thất bại.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
