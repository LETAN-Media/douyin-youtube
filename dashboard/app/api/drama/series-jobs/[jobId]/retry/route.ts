import { NextResponse } from "next/server";
import { DramaApiError, retryDramaJob } from "@/lib/drama-api";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ jobId: string }> },
) {
  try {
    const { jobId } = await params;
    if (!jobId) return NextResponse.json({ error: "Thiếu jobId." }, { status: 400 });
    const body = (await request.json().catch(() => null)) as {
      episode_numbers?: unknown;
      failed_only?: unknown;
    } | null;
    const episode_numbers = Array.isArray(body?.episode_numbers)
      ? body.episode_numbers.filter((n): n is number => typeof n === "number")
      : undefined;
    return NextResponse.json(
      await retryDramaJob(jobId, {
        episode_numbers,
        failed_only: body?.failed_only === true,
      }),
    );
  } catch (err: unknown) {
    const status = err instanceof DramaApiError ? err.status : 500;
    const message = err instanceof Error ? err.message : "Không retry được.";
    return NextResponse.json({ error: message, message }, { status });
  }
}
