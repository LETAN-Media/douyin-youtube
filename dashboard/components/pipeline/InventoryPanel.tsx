"use client";

import Link from "next/link";
import { useTransition } from "react";
import { useToast } from "@/components/Toast";
import {
  Badge,
  Card,
  CardHeader,
  EmptyState,
  btnSmall,
  inputCls,
} from "@/components/ui";
import { actionPublishNow } from "@/lib/actions";
import { formatDateTime } from "@/lib/format";
import type {
  Destination,
  DouyinSource,
  InventoryList,
} from "@/lib/types";

const STATUS_OPTIONS = ["all", "new", "backlog", "scheduled", "published"];

export function InventoryPanel({
  pipelineId,
  inventory,
  sources,
  destinations,
  current,
}: {
  pipelineId: string;
  inventory: InventoryList | null;
  sources: DouyinSource[];
  destinations: Destination[];
  current: { page: number; status: string; q: string; source_id: string };
}) {
  const { toast } = useToast();
  const [pending, start] = useTransition();

  const totalPages = inventory
    ? Math.max(1, Math.ceil(inventory.total / inventory.page_size))
    : 1;

  const pageLink = (page: number) => {
    const q = new URLSearchParams({ tab: "inventory", page: String(page) });
    if (current.status && current.status !== "all") q.set("status", current.status);
    if (current.q) q.set("q", current.q);
    if (current.source_id) q.set("source_id", current.source_id);
    return `/pipelines/${pipelineId}?${q.toString()}`;
  };

  return (
    <Card>
      <CardHeader
        title={`Inventory${inventory ? ` (${inventory.total})` : ""}`}
        subtitle="Mỗi video có publication matrix riêng theo từng destination"
      />
      {/* Filter bar: GET form, no JS needed */}
      <form
        method="get"
        action={`/pipelines/${pipelineId}`}
        className="grid gap-2 border-b border-slate-100 p-4 sm:grid-cols-[1fr_160px_180px_auto] sm:px-5"
      >
        <input type="hidden" name="tab" value="inventory" />
        <input
          name="q"
          defaultValue={current.q}
          placeholder="Tìm theo tiêu đề / video id…"
          className={inputCls}
        />
        <select name="status" defaultValue={current.status} className={inputCls}>
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <select name="source_id" defaultValue={current.source_id} className={inputCls}>
          <option value="">All sources</option>
          {sources.map((s) => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </select>
        <button type="submit" className={btnSmall}>
          Lọc
        </button>
      </form>

      {!inventory ? (
        <EmptyState title="Không tải được inventory" hint="Thử tải lại trang." />
      ) : inventory.items.length === 0 ? (
        <EmptyState
          title="Inventory trống"
          hint="Thêm Douyin source và Sync để quét video."
        />
      ) : (
        <>
          {/* Desktop table */}
          <div className="hidden overflow-x-auto md:block">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-5 py-2.5 font-semibold">Video</th>
                  <th className="px-3 py-2.5 font-semibold">Status</th>
                  <th className="px-3 py-2.5 font-semibold">Created</th>
                  <th className="px-3 py-2.5 text-right font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {inventory.items.map((v) => (
                  <tr key={v.id}>
                    <td className="max-w-md px-5 py-3">
                      <p className="truncate font-semibold text-slate-900">{v.title || v.video_id}</p>
                      <p className="mt-0.5 truncate text-xs text-slate-500">{v.url}</p>
                    </td>
                    <td className="px-3 py-3">
                      <StatusBadge status={v.status} backlog={v.is_backlog} />
                    </td>
                    <td className="whitespace-nowrap px-3 py-3 text-xs text-slate-600">
                      {formatDateTime(v.douyin_created_at ?? v.created_at)}
                    </td>
                    <td className="px-5 py-3">
                      <div className="flex justify-end gap-1.5">
                        <Link
                          href={`/pipelines/${pipelineId}/inventory/${v.id}`}
                          className={btnSmall}
                        >
                          Matrix
                        </Link>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {/* Mobile cards */}
          <div className="grid gap-3 p-4 md:hidden">
            {inventory.items.map((v) => (
              <div key={v.id} className="rounded-xl border border-slate-200 p-3">
                <p className="line-clamp-2 text-sm font-semibold text-slate-900">
                  {v.title || v.video_id}
                </p>
                <div className="mt-2 flex items-center gap-2">
                  <StatusBadge status={v.status} backlog={v.is_backlog} />
                  <span className="text-[11px] text-slate-500">
                    {formatDateTime(v.douyin_created_at ?? v.created_at)}
                  </span>
                </div>
                <div className="mt-3">
                  <Link
                    href={`/pipelines/${pipelineId}/inventory/${v.id}`}
                    className="block rounded-lg bg-indigo-600 px-3 py-2 text-center text-sm font-semibold text-white"
                  >
                    Publication matrix
                  </Link>
                  <div className="mt-2 flex gap-1.5 overflow-x-auto pb-1">
                    {destinations.slice(0, 4).map((d) => (
                      <button
                        key={d.id}
                        type="button"
                        disabled={pending || d.platform === "facebook"}
                        className={btnSmall}
                        onClick={() =>
                          start(async () => {
                            const r = await actionPublishNow(pipelineId, v.id, d.id);
                            toast(r.ok ? `Đã đẩy tới ${d.name}.` : r.error, r.ok ? "success" : "error");
                          })
                        }
                      >
                        → {d.name}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-between border-t border-slate-100 px-4 py-3 sm:px-5">
            <p className="text-xs text-slate-500">
              Page {inventory.page}/{totalPages} · {inventory.total} videos
            </p>
            <div className="flex gap-1.5">
              {inventory.page > 1 ? (
                <Link href={pageLink(inventory.page - 1)} className={btnSmall}>← Prev</Link>
              ) : null}
              {inventory.page < totalPages ? (
                <Link href={pageLink(inventory.page + 1)} className={btnSmall}>Next →</Link>
              ) : null}
            </div>
          </div>
        </>
      )}
    </Card>
  );
}

export function StatusBadge({
  status,
  backlog,
}: {
  status: string;
  backlog?: boolean;
}) {
  if (status === "published") return <Badge tone="green">published</Badge>;
  if (status === "scheduled") return <Badge tone="blue">scheduled</Badge>;
  if (status === "backlog" || backlog) return <Badge tone="amber">backlog</Badge>;
  return <Badge tone="slate">{status}</Badge>;
}
