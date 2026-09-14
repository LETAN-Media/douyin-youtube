"use client";

import { useTransition } from "react";
import { useRouter } from "next/navigation";
import { useToast } from "@/components/Toast";
import { Badge, btnSmall } from "@/components/ui";
import {
  actionPublishNow,
  actionReschedulePublication,
  actionRetryPublication,
  actionSkipPublication,
} from "@/lib/actions";
import { formatDateTime, platformLabel, publicationLabel } from "@/lib/format";
import type { Destination, Publication } from "@/lib/types";

export function MatrixActions({
  pipelineId,
  videoId,
  destination,
  publication,
}: {
  pipelineId: string;
  videoId: string;
  destination: Destination;
  publication: Publication | null;
}) {
  const { toast } = useToast();
  const [pending, start] = useTransition();
  const router = useRouter();
  const isFacebook = destination.platform === "facebook";

  const act = (
    fn: () => Promise<{ ok: true } | { ok: false; error: string }>,
    okMsg: string,
  ) => {
    if (pending) return;
    start(async () => {
      const r = await fn();
      toast(r.ok ? okMsg : r.error, r.ok ? "success" : "error");
      if (r.ok) router.refresh();
    });
  };

  const label = publication ? publicationLabel(publication.status) : { text: "Waiting", tone: "amber" as const };

  return (
    <div className="px-4 py-3 sm:px-5">
      <div className="flex flex-wrap items-center gap-2">
        <p className="min-w-0 flex-1 truncate text-sm font-bold text-slate-900">
          {destination.name}
          <span className="ml-2 text-xs font-medium text-slate-500">
            {platformLabel(destination.platform)}
          </span>
        </p>
        <Badge tone={label.tone}>{label.text}</Badge>
      </div>

      <p className="mt-1 text-xs text-slate-500">
        {publication?.scheduled_at ? `Scheduled: ${formatDateTime(publication.scheduled_at)}` : "Chưa lên lịch"}
        {publication?.error ? (
          <span className="mt-0.5 block break-words text-red-600">{publication.error}</span>
        ) : null}
        {isFacebook && !publication ? (
          <span className="mt-0.5 block font-medium text-amber-700">
            Facebook publishing adapter not configured
          </span>
        ) : null}
      </p>

      {/* Bottom actions: touch-friendly */}
      <div className="mt-2 flex flex-wrap gap-1.5">
        {!publication ? (
          <button
            type="button"
            className={btnSmall}
            disabled={pending || isFacebook}
            title={isFacebook ? "Facebook publishing adapter not configured" : undefined}
            onClick={() => act(() => actionPublishNow(pipelineId, videoId, destination.id), `Đã đẩy tới ${destination.name}.`)}
          >
            Publish now
          </button>
        ) : null}
        {publication && (publication.status === "failed" || publication.status === "skipped" || publication.status === "queued" || publication.status === "scheduled") ? (
          <button
            type="button"
            className={btnSmall}
            disabled={pending || isFacebook}
            onClick={() => act(() => actionRetryPublication(pipelineId, publication.id), "Đã retry.")}
          >
            Retry
          </button>
        ) : null}
        {publication && publication.status !== "published" && publication.status !== "skipped" ? (
          <button
            type="button"
            className={btnSmall}
            disabled={pending}
            onClick={() => act(() => actionSkipPublication(pipelineId, publication.id), "Đã skip.")}
          >
            Skip
          </button>
        ) : null}
        {publication && publication.status !== "published" ? (
          <button
            type="button"
            className={btnSmall}
            disabled={pending}
            onClick={() => {
              const v = window.prompt("Reschedule tới (YYYY-MM-DDTHH:mm):", "2026-09-15T08:00");
              if (!v) return;
              act(() => actionReschedulePublication(pipelineId, publication.id, v), "Đã reschedule.");
            }}
          >
            Reschedule
          </button>
        ) : null}
        {publication?.external_url ? (
          <a href={publication.external_url} target="_blank" rel="noreferrer" className={btnSmall}>
            Open →
          </a>
        ) : null}
      </div>
    </div>
  );
}
