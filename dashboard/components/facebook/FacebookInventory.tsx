"use client";

import { useMemo, useState, useCallback } from "react";
import { Card, CardHeader, Badge, btnSmall, btnPrimary, btnSecondary, btnDangerGhost } from "@/components/ui";
import { IconInventory, IconDrama } from "@/components/icons";
import type { FacebookInventoryDto } from "@/lib/facebook-api";

const STATUS_TONE: Record<string, string> = {
  new: "slate",
  queued: "amber",
  processing: "indigo",
  published: "green",
  failed: "red",
  skipped: "slate",
};

const STATUS_LABEL: Record<string, string> = {
  new: "New",
  queued: "Queued",
  processing: "Processing",
  published: "Published",
  failed: "Failed",
  skipped: "Skipped",
};

const PAGE_SIZE = 50;

const FILTERS = [
  { key: "", label: "Tất cả" },
  { key: "new", label: "Mới" },
  { key: "queued", label: "Đã xếp hàng" },
  { key: "processing", label: "Đang xử lý" },
  { key: "published", label: "Đã đăng" },
  { key: "skipped", label: "Bỏ qua" },
  { key: "failed", label: "Lỗi" },
];

function Thumbnail({ url, size = 80 }: { url: string | null; size?: number }) {
  const [errored, setErrored] = useState(false);
  if (!url || errored) {
    return (
      <div
        className="flex items-center justify-center rounded-xl bg-slate-100"
        style={{ width: size, height: size }}
      >
        <IconDrama size={size > 60 ? 24 : 16} className="text-slate-400" />
      </div>
    );
  }
  return (
    <img
      src={url}
      alt=""
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setErrored(true)}
      className="h-full w-full rounded-xl object-cover"
      style={{ width: size, height: size }}
    />
  );
}

function MobileCard({
  v,
  selected,
  onToggle,
  onSkip,
  onRestore,
}: {
  v: FacebookInventoryDto;
  selected: boolean;
  onToggle: () => void;
  onSkip: () => void;
  onRestore: () => void;
}) {
  const isSkipped = v.status === "skipped";
  const isPublished = v.status === "published";
  const isProcessing = v.status === "processing" || v.status === "queued";
  return (
    <div
      className={`flex gap-3 rounded-2xl border border-slate-200/90 bg-white p-3 shadow-[0_1px_2px_rgba(15,23,42,0.05)] ${isSkipped ? "opacity-75" : ""}`}
    >
      <div className="w-[110px] shrink-0">
        <div className="aspect-[9/16] w-full overflow-hidden rounded-xl bg-slate-100">
          <Thumbnail url={v.thumbnail_url} size={110} />
        </div>
      </div>
      <div className="flex-1 min-w-0">
        <p className="line-clamp-2 text-sm font-bold text-slate-900">
          {v.caption?.trim() ? v.caption : `Reel ${v.reel_id}`}
        </p>
        <p className="mt-1 truncate text-xs text-slate-500">FB: {v.reel_id}</p>
        <div className="mt-1.5">
          <Badge tone={STATUS_TONE[v.status] ?? "slate"}>{STATUS_LABEL[v.status] ?? v.status}</Badge>
        </div>
        <div className="mt-2 flex items-center justify-between gap-2">
          <label className="flex items-center gap-1.5 text-xs text-slate-600">
            <input
              type="checkbox"
              checked={selected}
              onChange={onToggle}
              disabled={isPublished || isProcessing}
              className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
            />
            Chọn
          </label>
          {isSkipped ? (
            <button
              type="button"
              onClick={onRestore}
              className="text-xs font-semibold text-indigo-600 transition hover:text-indigo-700"
            >
              Khôi phục
            </button>
          ) : !isPublished && !isProcessing ? (
            <button
              type="button"
              onClick={onSkip}
              className="text-xs font-semibold text-rose-600 transition hover:text-rose-700"
            >
              Bỏ qua
            </button>
          ) : null}
        </div>
      </div>
    </div>
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
  const [items, setItems] = useState<FacebookInventoryDto[]>(initialItems);
  const [total, setTotal] = useState(initialTotal);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filterStatus, setFilterStatus] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);

  const hasMore = items.length < total;

  const fetchUrl = useCallback(
    (status: string, limit: number, offset: number) => {
      const q = new URLSearchParams();
      q.set("pipelineId", pipelineId);
      q.set("limit", String(limit));
      q.set("offset", String(offset));
      if (status) q.set("status", status);
      return `/api/facebook/inventory?${q.toString()}`;
    },
    [pipelineId],
  );

  async function loadMore() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(fetchUrl(filterStatus, PAGE_SIZE, items.length), {
        cache: "no-store",
      });
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

  async function changeFilter(status: string) {
    setFilterStatus(status);
    setSelectedIds(new Set());
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(fetchUrl(status, PAGE_SIZE, 0), {
        cache: "no-store",
      });
      const data = (await res.json()) as {
        items?: FacebookInventoryDto[];
        total?: number;
        error?: string;
      };
      if (!res.ok) throw new Error(data.error ?? `HTTP ${res.status}`);
      setItems(data.items ?? []);
      setTotal(data.total ?? 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không tải được.");
    } finally {
      setLoading(false);
    }
  }

  const toggleSelect = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const allSelected = useMemo(
    () => items.length > 0 && items.every((v) => selectedIds.has(v.id)),
    [items, selectedIds],
  );

  const someSelected = useMemo(
    () => selectedIds.size > 0,
    [selectedIds],
  );

  function toggleAll() {
    if (allSelected) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(items.map((v) => v.id)));
    }
  }

  async function handleBulkSkip() {
    if (selectedIds.size === 0) return;
    setActionLoading(true);
    setConfirmOpen(false);
    try {
      const res = await fetch(
        `/api/facebook/pipelines/${encodeURIComponent(pipelineId)}/inventory/skip`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reel_ids: Array.from(selectedIds) }),
        },
      );
      const data = (await res.json()) as {
        ok?: boolean;
        skipped?: number;
        rejected?: string[];
        error?: string;
      };
      if (!res.ok) throw new Error(data.error ?? `HTTP ${res.status}`);
      const skippedIds = new Set(selectedIds);
      setItems((prev) => prev.filter((v) => !skippedIds.has(v.id)));
      setTotal((prev) => Math.max(0, prev - (data.skipped ?? skippedIds.size)));
      setSelectedIds(new Set());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bulk skip thất bại.");
    } finally {
      setActionLoading(false);
    }
  }

  async function handleSkipOne(v: FacebookInventoryDto) {
    setActionLoading(true);
    try {
      const res = await fetch(`/api/facebook/reels/${encodeURIComponent(v.id)}/skip`, {
        method: "POST",
      });
      const data = (await res.json()) as { ok?: boolean; status?: string; error?: string };
      if (!res.ok) throw new Error(data.error ?? `HTTP ${res.status}`);
      setItems((prev) => prev.filter((item) => item.id !== v.id));
      setTotal((prev) => Math.max(0, prev - 1));
      setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(v.id);
        return next;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Skip thất bại.");
    } finally {
      setActionLoading(false);
    }
  }

  async function handleRestoreOne(v: FacebookInventoryDto) {
    setActionLoading(true);
    try {
      const res = await fetch(`/api/facebook/reels/${encodeURIComponent(v.id)}/restore`, {
        method: "POST",
      });
      const data = (await res.json()) as { ok?: boolean; status?: string; error?: string };
      if (!res.ok) throw new Error(data.error ?? `HTTP ${res.status}`);
      setItems((prev) =>
        prev.map((item) => (item.id === v.id ? { ...item, status: data.status ?? "new" } : item)),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Restore thất bại.");
    } finally {
      setActionLoading(false);
    }
  }

  const actionBar = someSelected && !confirmOpen ? (
    <div className="sticky top-0 z-10 mb-3 flex items-center justify-between rounded-xl border border-indigo-100 bg-indigo-50/90 px-4 py-2.5 backdrop-blur">
      <span className="text-sm font-bold text-indigo-900">Đã chọn {selectedIds.size}</span>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setConfirmOpen(true)}
          disabled={actionLoading}
          className="inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-xl bg-rose-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-rose-500 disabled:cursor-not-allowed disabled:opacity-50 sm:min-h-[38px]"
        >
          {actionLoading ? "Đang xử lý…" : "Bỏ qua video"}
        </button>
        <button
          type="button"
          onClick={() => setSelectedIds(new Set())}
          disabled={actionLoading}
          className="inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 sm:min-h-[38px]"
        >
          Bỏ chọn
        </button>
      </div>
    </div>
  ) : null;

  const confirmModal = confirmOpen ? (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/50 p-4 backdrop-blur-[2px] sm:items-center">
      <div className="fade-up w-full max-w-sm rounded-3xl border border-slate-200 bg-white p-5 shadow-2xl">
        <h3 className="text-[15px] font-extrabold tracking-tight text-slate-900">
          Bỏ qua {selectedIds.size} video?
        </h3>
        <p className="mt-1 text-sm leading-relaxed text-slate-600">
          Các video này sẽ không được hệ thống tự động đăng lên YouTube. Bạn có thể khôi phục lại sau.
        </p>
        <div className="mt-4 flex gap-2">
          <button
            type="button"
            className={`${btnSecondary} flex-1`}
            disabled={actionLoading}
            onClick={() => setConfirmOpen(false)}
          >
            Hủy
          </button>
          <button
            type="button"
            className="inline-flex min-h-[44px] flex-1 items-center justify-center gap-1.5 rounded-xl bg-rose-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-rose-500 disabled:cursor-not-allowed disabled:opacity-50 sm:min-h-[38px]"
            disabled={actionLoading}
            onClick={handleBulkSkip}
          >
            {actionLoading ? "Đang xử lý…" : "Bỏ qua video"}
          </button>
        </div>
      </div>
    </div>
  ) : null;

  return (
    <Card>
      <CardHeader
        title={`Inventory (${total})`}
        subtitle="Video từ Facebook Fanpage"
        icon={<IconInventory size={16} />}
      />
      <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-2 overflow-x-auto">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            onClick={() => changeFilter(f.key)}
            className={`whitespace-nowrap rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
              filterStatus === f.key
                ? "bg-indigo-600 text-white shadow-sm"
                : "text-slate-600 hover:bg-slate-100"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>
      {actionBar}
      {confirmModal}
      {items.length === 0 ? (
        <div className="p-6 text-center text-sm text-slate-500">Inventory trống</div>
      ) : (
        <>
          {/* Mobile cards */}
          <div className="grid gap-3 p-4 md:hidden">
            {items.map((v) => (
              <MobileCard
                key={v.id}
                v={v}
                selected={selectedIds.has(v.id)}
                onToggle={() => toggleSelect(v.id)}
                onSkip={() => handleSkipOne(v)}
                onRestore={() => handleRestoreOne(v)}
              />
            ))}
          </div>
          {/* Desktop table */}
          <div className="hidden overflow-x-auto md:block">
            <table className="w-full text-sm">
              <thead className="bg-slate-50/70">
                <tr className="border-b border-slate-100 text-left text-[11px] uppercase tracking-[0.08em] text-slate-400">
                  <th className="w-10 px-3 py-3 font-bold">
                    <input
                      type="checkbox"
                      checked={allSelected}
                      onChange={toggleAll}
                      className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                    />
                  </th>
                  <th className="w-16 px-3 py-3 font-bold">Preview</th>
                  <th className="px-3 py-3 font-bold">Video</th>
                  <th className="px-3 py-3 font-bold">Facebook ID</th>
                  <th className="px-3 py-3 font-bold">Status</th>
                  <th className="px-3 py-3 font-bold">YouTube</th>
                  <th className="w-24 px-3 py-3 font-bold">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {items.map((v) => {
                  const isSkipped = v.status === "skipped";
                  const isPublished = v.status === "published";
                  const isProcessing = v.status === "processing" || v.status === "queued";
                  return (
                    <tr key={v.id} className={`transition hover:bg-indigo-50/40 ${isSkipped ? "opacity-75" : ""}`}>
                      <td className="px-3 py-3">
                        <input
                          type="checkbox"
                          checked={selectedIds.has(v.id)}
                          onChange={() => toggleSelect(v.id)}
                          disabled={isPublished || isProcessing}
                          className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                        />
                      </td>
                      <td className="px-3 py-3">
                        <div className="flex items-center justify-center">
                          <Thumbnail url={v.thumbnail_url} size={56} />
                        </div>
                      </td>
                      <td className="max-w-md px-3 py-3">
                        <p className="truncate text-sm font-bold text-slate-900">
                          {v.caption?.trim() ? v.caption : `Reel ${v.reel_id}`}
                        </p>
                        <div className="mt-1 flex flex-wrap gap-2 text-xs text-slate-500">
                          <span>FB: {v.reel_id}</span>
                          {v.youtube_video_id ? <span>YT: {v.youtube_video_id}</span> : null}
                        </div>
                        {v.last_error ? <p className="mt-1 text-xs text-rose-600">{v.last_error}</p> : null}
                      </td>
                      <td className="whitespace-nowrap px-3 py-3 text-xs text-slate-600">{v.reel_id}</td>
                      <td className="px-3 py-3">
                        <Badge tone={STATUS_TONE[v.status] ?? "slate"}>{STATUS_LABEL[v.status] ?? v.status}</Badge>
                      </td>
                      <td className="whitespace-nowrap px-3 py-3 text-xs text-slate-600">{v.youtube_video_id ?? "—"}</td>
                      <td className="whitespace-nowrap px-3 py-3">
                        {isSkipped ? (
                          <button
                            type="button"
                            onClick={() => handleRestoreOne(v)}
                            disabled={actionLoading}
                            className="text-xs font-semibold text-indigo-600 transition hover:text-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            Khôi phục
                          </button>
                        ) : isPublished || isProcessing ? (
                          <span className="text-xs text-slate-400">—</span>
                        ) : (
                          <button
                            type="button"
                            onClick={() => handleSkipOne(v)}
                            disabled={actionLoading}
                            className="text-xs font-semibold text-rose-600 transition hover:text-rose-700 disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            Bỏ qua
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="flex flex-col items-center gap-2 border-t border-slate-100 px-4 py-3">
            {error ? <p className="text-xs text-rose-600">{error}</p> : null}
            {hasMore ? (
              <button
                type="button"
                className={btnSmall}
                disabled={loading}
                onClick={loadMore}
              >
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
