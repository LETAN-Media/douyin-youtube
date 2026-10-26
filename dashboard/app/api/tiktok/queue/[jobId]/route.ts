import { NextResponse } from "next/server";
import {
  cancelTikTokQueueJob,
  rescheduleTikTokQueueJob,
  retryTikTokQueueJob,
  TikTokApiError,
} from "@/lib/tiktok-api";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ jobId: string }> },
) {
  try {
    const { jobId } = await params;
    if (!jobId) {
      return NextResponse.json({ error: "Thiếu jobId." }, { status: 400 });
    }
    const body = await request.json().catch(() => ({}));
    const action = body.action;

    if (action === "retry") {
      const res = await retryTikTokQueueJob(jobId);
      return NextResponse.json(res);
    }
    if (action === "cancel") {
      const res = await cancelTikTokQueueJob(jobId);
      return NextResponse.json(res);
    }
    if (action === "reschedule") {
      if (!body.scheduled_at) {
        return NextResponse.json({ error: "Thiếu scheduled_at." }, { status: 400 });
      }
      const res = await rescheduleTikTokQueueJob(jobId, body.scheduled_at);
      return NextResponse.json(res);
    }

    return NextResponse.json({ error: "Thao tác không hợp lệ." }, { status: 400 });
  } catch (err: unknown) {
    const status = err instanceof TikTokApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Thao tác hàng đợi thất bại.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
