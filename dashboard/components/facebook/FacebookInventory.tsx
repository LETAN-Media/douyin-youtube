"use client";

import { useState } from "react";
import { Card, CardHeader, Badge, btnSmall } from "@/components/ui";
import { IconInventory } from "@/components/icons";
import type { FacebookInventoryDto } from "@/lib/facebook-api";

const STATUS_TONE: Record<string, string> = {
  new: "slate",
  queued: "amber",
  processing: "indigo",
  published: "green",
  failed: "red",
  skipped: "slate",
};

const PAGE_SIZE = 50;

function Row({ v, detail }: { v: FacebookInventoryDto; detail: boolean }) {
  return (
    <>
      <p className="truncate text-sm font-bold text-slate-900">
        {v.caption?.trim() ? v.caption : `Reel ${v.reel_id}`}
      </p>
      <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">
        <span>FB: {v.reel_id}</span>
        {v.youtube_video_id ? <span>YT: {v.youtube_video_id}</span> : null}
        {detail ? (
          <>
            <span>Retry: {v.retry_count}</span>
            {v.discovered_at ? <span>Found: {new Date(v.discovered_at).toLocaleDateString()}</span> : null}
          </>
        ) : null}
      </div>
      {v.last_error ? <p className="mt-1 text-xs text-rose-600">{v.last_error}</p> : null}
    </>
  );
}

export function FacebookInventory({
  pipelineId,
  initialItems,
  initialTotal,
}: {
  pipelineId: string;
  initialItems: FacebookInventoryDto[];
  initialTotal: number;
}) {
  const [items, setItems] = useState(initialItems);
  const [total, setTotal] = useState(initialTotal);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const hasMore = items.length < total;

  async function loadMore() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/facebook/inventory?pipelineId=${encodeURIComponent(pipelineId)}&limit=${PAGE_SIZE}&offset=${items.length}`,
        { cache: "no-store" },
      );
      const data = (await res.json()) as {
        items?: FacebookInventoryDto[];
        total?: number;
        error?: string;
      };
      if (!res.ok) throw new Error(data.error ?? `HTTP ${res.status}`);
      setItems((prev) => [...prev, ...(data.items ?? [])]);
      setTotal(data.total ?? total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không tải thêm được.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title={`Inventory (${total})`}
        subtitle="Video từ Facebook Fanpage"
        icon={<IconInventory size={16} />}
      />
      {items.length === 0 ? (
        <div className="p-6 text-center text-sm text-slate-500">Inventory trống</div>
      ) : (
        <>
          <div className="hidden overflow-x-auto md:block">
            <table className="w-full text-sm">
              <thead className="bg-slate-50/70">
                <tr className="border-b border-slate-100 text-left text-[11px] uppercase tracking-[0.08em] text-slate-400">
                  <th className="px-5 py-3 font-bold">Video</th>
                  <th className="px-3 py-3 font-bold">Facebook ID</th>
                  <th className="px-3 py-3 font-bold">Status</th>
                  <th className="px-3 py-3 font-bold">YouTube ID</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {items.map((v) => (
                  <tr key={v.id} className="transition hover:bg-indigo-50/40">
                    <td className="max-w-md px-5 py-3">
                      <Row v={v} detail={false} />
                    </td>
                    <td className="whitespace-nowrap px-3 py-3 text-xs text-slate-600">{v.reel_id}</td>
                    <td className="px-3 py-3">
                      <Badge tone={STATUS_TONE[v.status] ?? "slate"}>{v.status}</Badge>
                    </td>
                    <td className="whitespace-nowrap px-3 py-3 text-xs text-slate-600">{v.youtube_video_id ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="grid gap-3 p-4 md:hidden">
            {items.map((v) => (
              <div key={v.id} className="rounded-2xl border border-slate-200/90 bg-white p-3.5 shadow-[0_1px_2px_rgba(15,23,42,0.05)]">
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <Row v={v} detail={false} />
                  </div>
                  <Badge tone={STATUS_TONE[v.status] ?? "slate"}>{v.status}</Badge>
                </div>
              </div>
            ))}
          </div>
          <div className="flex flex-col items-center gap-2 border-t border-slate-100 px-4 py-3">
            {error ? <p className="text-xs text-rose-600">{error}</p> : null}
            {hasMore ? (
              <button type="button" className={btnSmall} disabled={loading} onClick={loadMore}>
                {loading ? "Đang tải…" : `Xem thêm (${items.length}/${total})`}
              </button>
            ) : (
              <p className="text-xs text-slate-400">Đã hiện tất cả {total} video.</p>
            )}
          </div>
        </>
      )}
    </Card>
  );
}
