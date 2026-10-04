"use client";

import { useState } from "react";
import { Card, CardHeader, Badge, btnSmall } from "@/components/ui";
import { IconPublications } from "@/components/icons";
import type { FacebookPublicationDto } from "@/lib/facebook-api";

const PAGE_SIZE = 100;

export function FacebookPublications({
  pipelineId,
  initialItems,
  initialTotal,
}: {
  pipelineId: string;
  initialItems: FacebookPublicationDto[];
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
        `/api/facebook/publications?pipelineId=${encodeURIComponent(pipelineId)}&limit=${PAGE_SIZE}&offset=${items.length}`,
        { cache: "no-store" },
      );
      const data = (await res.json()) as {
        items?: FacebookPublicationDto[];
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
        title={`Publications (${total})`}
        subtitle="Lịch sử đăng video từ Facebook lên YouTube"
        icon={<IconPublications size={16} />}
      />
      {items.length === 0 ? (
        <div className="p-6 text-center text-sm text-slate-500">Chưa có publication</div>
      ) : (
        <>
          <div className="space-y-3 p-4 sm:px-5">
            {items.map((p) => (
              <div key={p.id} className="rounded-2xl border border-slate-200/90 bg-white p-4 shadow-[0_1px_2px_rgba(15,23,42,0.05)]">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-bold text-slate-900">
                      {p.reel_id} → {p.youtube_video_id || "..."}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      {p.channel_name ? `${p.channel_name} · ` : ""}
                      Published: {p.published_at ? new Date(p.published_at).toLocaleString() : "—"}
                    </p>
                    {p.last_error ? (
                      <p className="mt-1 text-xs text-rose-600">{p.last_error}</p>
                    ) : null}
                  </div>
                  <Badge tone={p.status === "published" ? "green" : p.status === "failed" ? "red" : "amber"}>
                    {p.status}
                  </Badge>
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
            ) : null}
          </div>
        </>
      )}
    </Card>
  );
}
