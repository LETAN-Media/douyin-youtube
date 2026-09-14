"use client";

import { useState, useTransition } from "react";
import Link from "next/link";
import { useToast } from "@/components/Toast";
import { ConfirmButton } from "@/components/ConfirmButton";
import {
  Badge,
  Card,
  CardHeader,
  EmptyState,
  btnPrimary,
  btnSecondary,
  btnSmall,
  inputCls,
  labelCls,
} from "@/components/ui";
import {
  actionCreateSource,
  actionDeleteSource,
  actionSyncPipeline,
  actionSyncSource,
  actionToggleSource,
} from "@/lib/actions";
import { formatDateTime } from "@/lib/format";
import type { DouyinSource } from "@/lib/types";

export function SourcesPanel({
  pipelineId,
  sources,
}: {
  pipelineId: string;
  sources: DouyinSource[];
}) {
  const { toast } = useToast();
  const [pending, start] = useTransition();
  const [showAdd, setShowAdd] = useState(false);

  const run = (fn: () => Promise<{ ok: true } | { ok: false; error: string }>, okMsg: string) =>
    start(async () => {
      const r = await fn();
      toast(r.ok ? okMsg : r.error, r.ok ? "success" : "error");
    });

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title={`Douyin Sources (${sources.length})`}
          subtitle="Paste profile URL → Sync Now → View Inventory"
          action={
            <div className="flex gap-2">
              <button
                type="button"
                className={btnSmall}
                disabled={pending}
                onClick={() => run(() => actionSyncPipeline(pipelineId), "Đã sync tất cả sources.")}
              >
                {pending ? "…" : "Sync all"}
              </button>
              <button
                type="button"
                className={btnSmall}
                onClick={() => setShowAdd((v) => !v)}
              >
                + Add Douyin Source
              </button>
            </div>
          }
        />
        {showAdd ? (
          <form
            className="grid gap-3 border-b border-slate-100 p-4 sm:grid-cols-[1fr_2fr_auto] sm:items-end sm:px-5"
            onSubmit={(e) => {
              e.preventDefault();
              const form = new FormData(e.currentTarget);
              start(async () => {
                const r = await actionCreateSource(pipelineId, form);
                toast(r.ok ? "Đã thêm source." : r.error, r.ok ? "success" : "error");
                if (r.ok) {
                  (e.target as HTMLFormElement).reset();
                  setShowAdd(false);
                }
              });
            }}
          >
            <div>
              <label className={labelCls} htmlFor="src-name">Name</label>
              <input id="src-name" name="name" required placeholder="Kênh A" className={inputCls} />
            </div>
            <div>
              <label className={labelCls} htmlFor="src-url">Profile URL</label>
              <input
                id="src-url"
                name="profile_url"
                required
                placeholder="https://www.douyin.com/user/..."
                className={inputCls}
              />
            </div>
            <button type="submit" disabled={pending} className={btnPrimary}>
              {pending ? "…" : "Add"}
            </button>
          </form>
        ) : null}

        {sources.length === 0 ? (
          <EmptyState
            title="Chưa có Douyin source"
            hint="Thêm profile URL Douyin để bắt đầu quét inventory."
          />
        ) : (
          <>
            {/* Desktop table */}
            <div className="hidden overflow-x-auto md:block">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-slate-500">
                    <th className="px-5 py-2.5 font-semibold">Name</th>
                    <th className="px-3 py-2.5 font-semibold">Profile</th>
                    <th className="px-3 py-2.5 font-semibold">Sync</th>
                    <th className="px-3 py-2.5 font-semibold">Last sync</th>
                    <th className="px-3 py-2.5 text-right font-semibold">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {sources.map((s) => (
                    <tr key={s.id} className="align-top">
                      <td className="px-5 py-3">
                        <p className="font-semibold text-slate-900">{s.name}</p>
                        <p className="mt-0.5">
                          {s.enabled ? <Badge tone="green">Enabled</Badge> : <Badge tone="slate">Disabled</Badge>}
                        </p>
                      </td>
                      <td className="max-w-56 px-3 py-3">
                        <p className="break-all text-xs text-slate-600">{s.profile_url ?? "—"}</p>
                        {s.douyin_sec_uid ? (
                          <p className="mt-1 text-[11px] text-slate-400">sec_uid: {s.douyin_sec_uid.slice(0, 18)}…</p>
                        ) : null}
                      </td>
                      <td className="px-3 py-3">
                        <SyncBadge status={s.inventory_sync_status} />
                      </td>
                      <td className="whitespace-nowrap px-3 py-3 text-xs text-slate-600">
                        {formatDateTime(s.last_checked_at)}
                      </td>
                      <td className="px-5 py-3">
                        <div className="flex flex-wrap justify-end gap-1.5">
                          <button type="button" className={btnSmall} disabled={pending}
                            onClick={() => run(() => actionSyncSource(pipelineId, s.id), "Sync xong.")}>
                            Sync Now
                          </button>
                          <Link
                            href={`/pipelines/${pipelineId}?tab=inventory&source_id=${s.id}`}
                            className={btnSmall}
                          >
                            View Inventory
                          </Link>
                          <button type="button" className={btnSmall} disabled={pending}
                            onClick={() => run(() => actionToggleSource(pipelineId, s.id, !s.enabled), s.enabled ? "Đã disable." : "Đã enable.")}>
                            {s.enabled ? "Disable" : "Enable"}
                          </button>
                          <ConfirmButton
                            title="Xóa source?"
                            message={`Xóa "${s.name}"? Inventory của source này cũng bị xóa.`}
                            onConfirm={() => actionDeleteSource(pipelineId, s.id)}
                          />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {/* Mobile cards */}
            <div className="grid gap-3 p-4 md:hidden">
              {sources.map((s) => (
                <div key={s.id} className="rounded-xl border border-slate-200 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <p className="min-w-0 truncate font-semibold text-slate-900">{s.name}</p>
                    {s.enabled ? <Badge tone="green">On</Badge> : <Badge tone="slate">Off</Badge>}
                  </div>
                  <p className="mt-1 break-all text-xs text-slate-500">{s.profile_url ?? "—"}</p>
                  <div className="mt-2 flex items-center gap-2 text-xs text-slate-500">
                    <SyncBadge status={s.inventory_sync_status} />
                    <span>· {formatDateTime(s.last_checked_at)}</span>
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-1.5">
                    <button type="button" className={btnSmall} disabled={pending}
                      onClick={() => run(() => actionSyncSource(pipelineId, s.id), "Sync xong.")}>
                      Sync Now
                    </button>
                    <Link href={`/pipelines/${pipelineId}?tab=inventory&source_id=${s.id}`} className={btnSmall}>
                      Inventory
                    </Link>
                    <button type="button" className={btnSmall} disabled={pending}
                      onClick={() => run(() => actionToggleSource(pipelineId, s.id, !s.enabled), "OK")}>
                      {s.enabled ? "Disable" : "Enable"}
                    </button>
                    <ConfirmButton title="Xóa source?" message={`Xóa "${s.name}"?`} onConfirm={() => actionDeleteSource(pipelineId, s.id)} />
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </Card>
    </div>
  );
}

function SyncBadge({ status }: { status: string }) {
  const tone =
    status === "completed" ? "green" : status === "failed" ? "red" : status === "syncing" || status === "queued" ? "amber" : "slate";
  return <Badge tone={tone}>{status}</Badge>;
}

export function AddSourceButtonPlaceholder() {
  return <button type="button" className={btnSecondary}>Add</button>;
}
