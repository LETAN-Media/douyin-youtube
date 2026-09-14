"use client";

import Link from "next/link";
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { useToast } from "@/components/Toast";
import {
  Badge,
  Card,
  CardHeader,
  EmptyState,
  btnSmall,
} from "@/components/ui";
import {
  actionReschedulePublication,
  actionRetryPublication,
  actionSkipPublication,
} from "@/lib/actions";
import { formatDateTime, publicationLabel } from "@/lib/format";
import type { Destination, Publication } from "@/lib/types";

const FILTERS = ["all", "queued", "scheduled", "published", "failed", "skipped"];

export function PublicationsPanel({
  pipelineId,
  publications,
  destinations,
  currentFilter,
}: {
  pipelineId: string;
  publications: Publication[];
  destinations: Destination[];
  currentFilter: string;
}) {
  const { toast } = useToast();
  const router = useRouter();
  const [, start] = useTransition();
  const [pendingKey, setPendingKey] = useState<string | null>(null);

  const destName = new Map(destinations.map((d) => [d.id, d.name]));

  const act = (
    key: string,
    fn: () => Promise<{ ok: true } | { ok: false; error: string }>,
    okMsg: string,
  ) => {
    if (pendingKey) return;
    setPendingKey(key);
    start(async () => {
      const r = await fn();
      setPendingKey(null);
      toast(r.ok ? okMsg : r.error, r.ok ? "success" : "error");
      if (r.ok) router.refresh();
    });
  };

  return (
    <Card>
      <CardHeader
        title={`Publications (${publications.length})`}
        subtitle="Action áp dụng đúng destination, không ảnh hưởng destination khác"
        action={
          <div className="flex flex-wrap gap-1">
            {FILTERS.map((f) => (
              <Link
                key={f}
                href={`/pipelines/${pipelineId}?tab=publications${f === "all" ? "" : `&pub_status=${f}`}`}
                className={`inline-flex min-h-[44px] items-center rounded-lg px-2.5 py-1.5 text-xs font-semibold sm:min-h-[32px] ${
                  currentFilter === f
                    ? "bg-indigo-600 text-white"
                    : "border border-slate-200 text-slate-600 hover:bg-slate-50"
                }`}
              >
                {f}
              </Link>
            ))}
          </div>
        }
      />
      {publications.length === 0 ? (
        <EmptyState title="Chưa có publication" hint="Scheduler sẽ tạo publications theo lịch của từng destination." />
      ) : (
        <>
          {/* Desktop */}
          <div className="hidden overflow-x-auto md:block">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-5 py-2.5 font-semibold">Destination</th>
                  <th className="px-3 py-2.5 font-semibold">Status</th>
                  <th className="px-3 py-2.5 font-semibold">Scheduled</th>
                  <th className="px-3 py-2.5 font-semibold">Error</th>
                  <th className="px-3 py-2.5 text-right font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {publications.slice(0, 100).map((p) => {
                  const label = publicationLabel(p.status);
                  return (
                    <tr key={p.id}>
                      <td className="px-5 py-3">
                        <p className="font-semibold text-slate-900">{destName.get(p.destination_id) ?? p.platform}</p>
                        <p className="text-[11px] text-slate-500">{p.platform} · attempts {p.attempts}</p>
                      </td>
                      <td className="px-3 py-3"><Badge tone={label.tone}>{label.text}</Badge></td>
                      <td className="whitespace-nowrap px-3 py-3 text-xs text-slate-600">
                        {formatDateTime(p.scheduled_at)}
                      </td>
                      <td className="max-w-56 truncate px-3 py-3 text-xs text-red-600">
                        {p.error ?? "—"}
                      </td>
                      <td className="px-5 py-3">
                        <div className="flex flex-wrap justify-end gap-1.5">
                          {p.status === "failed" || p.status === "skipped" ? (
                            <button type="button" className={btnSmall} disabled={pendingKey !== null}
                              onClick={() => act(`retry:${p.id}`, () => actionRetryPublication(pipelineId, p.id), "Đã retry.")}>
                              {pendingKey === `retry:${p.id}` ? "…" : "Retry"}
                            </button>
                          ) : null}
                          {p.status !== "published" && p.status !== "skipped" ? (
                            <button type="button" className={btnSmall} disabled={pendingKey !== null}
                              onClick={() => act(`skip:${p.id}`, () => actionSkipPublication(pipelineId, p.id), "Đã skip.")}>
                              {pendingKey === `skip:${p.id}` ? "…" : "Skip"}
                            </button>
                          ) : null}
                          {p.status !== "published" ? (
                            <button type="button" className={btnSmall} disabled={pendingKey !== null}
                              onClick={() => {
                                const v = window.prompt("Reschedule tới (YYYY-MM-DDTHH:mm):", "2026-09-15T08:00");
                                if (!v) return;
                                act(`resched:${p.id}`, () => actionReschedulePublication(pipelineId, p.id, v), "Đã reschedule.");
                              }}>
                              Reschedule
                            </button>
                          ) : null}
                          {p.external_url ? (
                            <a href={p.external_url} target="_blank" rel="noreferrer" className={btnSmall}>Open</a>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {/* Mobile cards */}
          <div className="grid gap-3 p-4 md:hidden">
            {publications.slice(0, 100).map((p) => {
              const label = publicationLabel(p.status);
              return (
                <div key={p.id} className="rounded-xl border border-slate-200 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="truncate text-sm font-bold">{destName.get(p.destination_id) ?? p.platform}</p>
                    <Badge tone={label.tone}>{label.text}</Badge>
                  </div>
                  <p className="mt-1 text-xs text-slate-500">
                    {formatDateTime(p.scheduled_at)}
                    {p.error ? <span className="mt-1 block break-words text-red-600">{p.error}</span> : null}
                  </p>
                  <div className="mt-2 grid grid-cols-3 gap-1.5">
                    {p.status === "failed" || p.status === "skipped" ? (
                      <button type="button" className={btnSmall} disabled={pendingKey !== null}
                        onClick={() => act(`retry:${p.id}`, () => actionRetryPublication(pipelineId, p.id), "Đã retry.")}>
                        {pendingKey === `retry:${p.id}` ? "…" : "Retry"}
                      </button>
                    ) : null}
                    {p.status !== "published" && p.status !== "skipped" ? (
                      <button type="button" className={btnSmall} disabled={pendingKey !== null}
                        onClick={() => act(`skip:${p.id}`, () => actionSkipPublication(pipelineId, p.id), "Đã skip.")}>
                        {pendingKey === `skip:${p.id}` ? "…" : "Skip"}
                      </button>
                    ) : null}
                    {p.status !== "published" ? (
                      <button type="button" className={btnSmall} disabled={pendingKey !== null}
                        onClick={() => {
                          const v = window.prompt("Reschedule tới (YYYY-MM-DDTHH:mm):", "2026-09-15T08:00");
                          if (!v) return;
                          act(`resched:${p.id}`, () => actionReschedulePublication(pipelineId, p.id, v), "Đã reschedule.");
                        }}>
                        Resched.
                      </button>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </Card>
  );
}
