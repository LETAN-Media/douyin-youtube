import { NextResponse } from "next/server";
import {
  generateTikTokScheduleSlots,
  getTikTokSchedule,
  getTikTokScheduleSlots,
  runTikTokScheduleBatchNow,
  toggleTikTokScheduleEnabled,
  updateTikTokScheduleSettings,
  TikTokApiError,
} from "@/lib/tiktok-api";

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const pipelineId = searchParams.get("pipeline_id");
    if (!pipelineId) {
      return NextResponse.json({ error: "Thiếu pipeline_id." }, { status: 400 });
    }
    const schedule = await getTikTokSchedule(pipelineId);
    let slots: any[] = [];
    try {
      slots = await getTikTokScheduleSlots(pipelineId);
    } catch {
      slots = [];
    }
    return NextResponse.json({ schedule, slots });
  } catch (err: unknown) {
    const status = err instanceof TikTokApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không tải được lịch đăng.";
    return NextResponse.json({ error: message, message }, { status });
  }
}

export async function PATCH(request: Request) {
  try {
    const body = await request.json().catch(() => ({}));
    const { pipeline_id, action, enabled } = body;
    if (!pipeline_id) {
      return NextResponse.json({ error: "Thiếu pipeline_id." }, { status: 400 });
    }

    if (action === "run_now") {
      const res = await runTikTokScheduleBatchNow(pipeline_id, body.destination_id);
      return NextResponse.json(res);
    }

    if (action === "update_settings") {
      const updated = await updateTikTokScheduleSettings(pipeline_id, body.settings || {});
      return NextResponse.json(updated);
    }

    if (action === "generate_slots") {
      const result = await generateTikTokScheduleSlots(pipeline_id);
      return NextResponse.json(result);
    }

    if (typeof enabled === "boolean") {
      const updated = await toggleTikTokScheduleEnabled(pipeline_id, enabled);
      return NextResponse.json(updated);
    }

    return NextResponse.json({ error: "Thao tác không hợp lệ." }, { status: 400 });
  } catch (err: unknown) {
    const status = err instanceof TikTokApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không cập nhật được lịch đăng.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
