"use client";

import { useEffect, useMemo, useState } from "react";
import { Badge, Card, CardHeader, Spinner, btnPrimary, btnSecondary, btnSmall, inputCls } from "@/components/ui";
import { IconAlert, IconCheck, IconRefresh, IconTrash, IconVideo, IconX } from "@/components/icons";
import type { TikTokReelDto, TikTokSourceDto } from "@/lib/tiktok-api";

interface Props {
  pipelineId: string;
  sources: TikTokSourceDto[];
  initialSelectedSourceId?: string;
  onInventoryChanged?: () => void;
}

function formatDuration(sec: number | null): string {
  if (sec === null || sec === undefined || Number.isNaN(sec)) return "—";
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function TikTokInventory({
  pipelineId,
  sources,
  initialSelectedSourceId,
  onInventoryChanged,
}: Props) {
  const [selectedSourceId, setSelectedSourceId] = useState<string>(
    initialSelectedSourceId || sources[0]?.id || "",
  );
  const [inventory, setInventory] = useState<TikTokReelDto[]>([]);
  const [loading, setLoading] = useState(false);
  const [filterStatus, setFilterStatus] = useState<"all" | "available" | "published" | "excluded">("all");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

  // Action states
  const [actionLoading, setActionLoading] = useState(false);
  const [actionJobId, setActionJobId] = useState<string | null>(null);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  // Modal confirmation state
  const [confirmModal, setConfirmModal] = useState<{
    type: "single" | "bulk";
    reel?: TikTokReelDto;
    ids?: string[];
  } | null>(null);

  // Load inventory for selected source
  async function loadInventory(sourceId: string) {
    if (!sourceId) return;
    setLoading(true);
    setSelectedIds([]);
    try {
      const res = await fetch(`/api/tiktok/inventory?source_id=${encodeURIComponent(sourceId)}`);
      if (res.ok) {
        const data = await res.json();
        setInventory(Array.isArray(data) ? data : []);
      } else {
        const err = await res.json().catch(() => ({}));
        setMessage({ type: "error", text: err.error || "Không thể tải danh sách video." });
      }
    } catch {
      setMessage({ type: "error", text: "Lỗi kết nối khi tải kho video." });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (initialSelectedSourceId && initialSelectedSourceId !== selectedSourceId) {
      setSelectedSourceId(initialSelectedSourceId);
    }
  }, [initialSelectedSourceId, selectedSourceId]);

  useEffect(() => {
    if (selectedSourceId) {
      void loadInventory(selectedSourceId);
    } else if (sources.length > 0 && sources[0]?.id) {
      setSelectedSourceId(sources[0].id);
      void loadInventory(sources[0].id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSourceId, sources]);

  // Filter inventory
  const filteredInventory = useMemo(() => {
    if (filterStatus === "all") return inventory;
    if (filterStatus === "available") {
      return inventory.filter((r) => r.status === "new" || r.status === "failed" || r.status === "error");
    }
    if (filterStatus === "published") {
      return inventory.filter((r) => r.status === "published");
    }
    if (filterStatus === "excluded") {
      return inventory.filter((r) => r.status === "excluded");
    }
    return inventory;
  }, [inventory, filterStatus]);

  // Count by status
  const counts = useMemo(() => {
    let available = 0;
    let published = 0;
    let excluded = 0;
    for (const r of inventory) {
      if (r.status === "published") published++;
      else if (r.status === "excluded") excluded++;
      else if (r.status === "new" || r.status === "failed" || r.status === "error") available++;
    }
    return { all: inventory.length, available, published, excluded };
  }, [inventory]);

  // Checkbox handlers
  const selectableReels = useMemo(() => {
    return filteredInventory.filter((r) => r.status !== "processing");
  }, [filteredInventory]);

  const allSelected = selectableReels.length > 0 && selectableReels.every((r) => selectedIds.includes(r.id));
  const isIndeterminate = selectedIds.length > 0 && !allSelected;

  function handleToggleSelectAll() {
    if (allSelected) {
      setSelectedIds([]);
    } else {
      setSelectedIds(selectableReels.map((r) => r.id));
    }
  }

  function handleToggleSelectOne(id: string) {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id],
    );
  }

  // Open single delete confirmation
  function handleRequestDelete(reel: TikTokReelDto) {
    if (reel.status === "processing") {
      setMessage({ type: "error", text: "Video đang trong quá trình xuất bản (processing), không thể xóa." });
      return;
    }
    setConfirmModal({ type: "single", reel });
  }

  // Open bulk delete confirmation
  function handleRequestBulkDelete() {
    if (selectedIds.length === 0) return;
    setConfirmModal({ type: "bulk", ids: selectedIds });
  }

  // Execute single delete/exclude
  async function executeSingleDelete(reelId: string) {
    setActionLoading(true);
    setActionJobId(reelId);
    setMessage(null);
    try {
      const res = await fetch("/api/tiktok/inventory", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reel_id: reelId, pipeline_id: pipelineId }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || data.detail || "Xóa video thất bại.");
      }
      setMessage({ type: "success", text: "Đã loại bỏ video khỏi kho thành công." });
      setConfirmModal(null);
      setSelectedIds((prev) => prev.filter((id) => id !== reelId));
      await loadInventory(selectedSourceId);
      onInventoryChanged?.();
    } catch (err) {
      setMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Xóa video thất bại.",
      });
    } finally {
      setActionLoading(false);
      setActionJobId(null);
    }
  }

  // Execute bulk delete/exclude
  async function executeBulkDelete(reelIds: string[]) {
    setActionLoading(true);
    setMessage(null);
    try {
      const res = await fetch("/api/tiktok/inventory", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reel_ids: reelIds, pipeline_id: pipelineId }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || data.detail || "Xóa hàng loạt video thất bại.");
      }
      const count = data.excluded ?? reelIds.length;
      setMessage({
        type: "success",
        text: `Đã loại bỏ ${count} video khỏi kho thành công.`,
      });
      setConfirmModal(null);
      setSelectedIds([]);
      await loadInventory(selectedSourceId);
      onInventoryChanged?.();
    } catch (err) {
      setMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Xóa hàng loạt video thất bại.",
      });
    } finally {
      setActionLoading(false);
    }
  }

  // Restore single reel
  async function handleRestoreReel(reelId: string) {
    setActionLoading(true);
    setActionJobId(reelId);
    setMessage(null);
    try {
      const res = await fetch("/api/tiktok/inventory", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "restore", reel_id: reelId, pipeline_id: pipelineId }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || data.detail || "Khôi phục video thất bại.");
      }
      setMessage({ type: "success", text: "Đã khôi phục video về kho thành công." });
      await loadInventory(selectedSourceId);
      onInventoryChanged?.();
    } catch (err) {
      setMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Khôi phục video thất bại.",
      });
    } finally {
      setActionLoading(false);
      setActionJobId(null);
    }
  }

  // Bulk restore selected reels
  async function handleBulkRestore() {
    if (selectedIds.length === 0) return;
    setActionLoading(true);
    setMessage(null);
    try {
      const res = await fetch("/api/tiktok/inventory", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "restore", reel_ids: selectedIds, pipeline_id: pipelineId }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || data.detail || "Khôi phục video thất bại.");
      }
      const count = data.restored ?? selectedIds.length;
      setMessage({ type: "success", text: `Đã khôi phục ${count} video về kho thành công.` });
      setSelectedIds([]);
      await loadInventory(selectedSourceId);
      onInventoryChanged?.();
    } catch (err) {
      setMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Khôi phục video thất bại.",
      });
    } finally {
      setActionLoading(false);
    }
  }

  return (
    <div className="space-y-4">
      {/* Alert Message */}
      {message && (
        <div
          className={`flex items-center justify-between rounded-2xl p-4 text-xs font-semibold shadow-sm transition ${
            message.type === "success"
              ? "border border-emerald-200 bg-emerald-50 text-emerald-800"
              : "border border-rose-200 bg-rose-50 text-rose-800"
          }`}
        >
          <div className="flex items-center gap-2">
            {message.type === "success" ? <IconCheck size={16} /> : <IconAlert size={16} />}
            <span>{message.text}</span>
          </div>
          <button
            type="button"
            onClick={() => setMessage(null)}
            className="ml-3 text-slate-400 hover:text-slate-600"
          >
            ✕
          </button>
        </div>
      )}

      {/* Main Inventory Card */}
      <Card className="rounded-2xl border border-slate-200/90 bg-white p-0 shadow-sm overflow-hidden">
        {/* Card Header & Controls */}
        <div className="p-4 sm:p-5 border-b border-slate-100 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-base font-extrabold text-slate-900 flex items-center gap-2">
              <IconVideo size={18} />
              Kho video TikTok (Inventory)
            </h2>
            <p className="mt-0.5 text-xs text-slate-500">
              Quản lý các video đã quét từ creator; loại bỏ video không muốn đăng hoặc khôi phục lại
            </p>
          </div>

          <div className="flex items-center gap-2">
            <select
              value={selectedSourceId}
              onChange={(e) => {
                setSelectedSourceId(e.target.value);
                void loadInventory(e.target.value);
              }}
              className={`${inputCls} text-xs py-1.5`}
            >
              {sources.map((s) => (
                <option key={s.id} value={s.id}>
                  @{s.username}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => void loadInventory(selectedSourceId)}
              className={btnSmall}
              disabled={loading}
              title="Làm mới kho video"
            >
              <IconRefresh size={14} />
            </button>
          </div>
        </div>

        {/* Filter Pills & Multi-select Actions Bar */}
        <div className="px-4 py-3 bg-slate-50/70 border-b border-slate-100 flex flex-col gap-2.5 sm:flex-row sm:items-center sm:justify-between">
          {/* Status Filter Tabs */}
          <div className="flex flex-wrap items-center gap-1.5">
            {[
              { id: "all", label: "Tất cả", count: counts.all },
              { id: "available", label: "Trong kho", count: counts.available },
              { id: "published", label: "Đã đăng", count: counts.published },
              { id: "excluded", label: "Đã loại trừ", count: counts.excluded },
            ].map((tab) => {
              const active = filterStatus === tab.id;
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => {
                    setFilterStatus(tab.id as any);
                    setSelectedIds([]);
                  }}
                  className={`inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-bold transition ${
                    active
                      ? "bg-indigo-600 text-white shadow-sm"
                      : "bg-white text-slate-600 border border-slate-200 hover:bg-slate-100"
                  }`}
                >
                  <span>{tab.label}</span>
                  <span
                    className={`rounded-full px-1.5 py-0.2 text-[10px] font-bold ${
                      active ? "bg-indigo-700 text-white" : "bg-slate-100 text-slate-500"
                    }`}
                  >
                    {tab.count}
                  </span>
                </button>
              );
            })}
          </div>

          {/* Bulk Action Controls */}
          {selectedIds.length > 0 && (
            <div className="flex items-center gap-2 animate-fadeIn">
              <span className="text-xs font-extrabold text-indigo-700 bg-indigo-50 border border-indigo-200 rounded-xl px-2.5 py-1">
                Đã chọn {selectedIds.length} video
              </span>

              {filterStatus === "excluded" ? (
                <button
                  type="button"
                  disabled={actionLoading}
                  onClick={handleBulkRestore}
                  className="inline-flex min-h-[34px] items-center gap-1 rounded-xl bg-emerald-600 px-3 py-1 text-xs font-bold text-white shadow-sm hover:bg-emerald-700 transition disabled:opacity-50"
                >
                  {actionLoading ? <Spinner size={12} /> : <IconCheck size={14} />}
                  <span>Khôi phục đã chọn</span>
                </button>
              ) : (
                <button
                  type="button"
                  disabled={actionLoading}
                  onClick={handleRequestBulkDelete}
                  className="inline-flex min-h-[34px] items-center gap-1 rounded-xl bg-rose-600 px-3 py-1 text-xs font-bold text-white shadow-sm hover:bg-rose-700 transition disabled:opacity-50"
                >
                  <IconTrash size={14} />
                  <span>Xóa đã chọn</span>
                </button>
              )}

              <button
                type="button"
                onClick={() => setSelectedIds([])}
                className="rounded-xl border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-50"
              >
                Bỏ chọn
              </button>
            </div>
          )}
        </div>

        {/* Video Table */}
        <div className="overflow-x-auto">
          {loading ? (
            <div className="py-16 text-center text-sm text-slate-500 flex items-center justify-center gap-2">
              <Spinner size={16} />
              <span>Đang tải kho video…</span>
            </div>
          ) : filteredInventory.length === 0 ? (
            <div className="py-16 text-center text-sm text-slate-500">
              {inventory.length === 0
                ? "Nguồn này chưa có video nào trong kho. Hãy bấm 'Quét' ở tab Nguồn video."
                : `Không có video nào ở mục "${
                    filterStatus === "available"
                      ? "Trong kho"
                      : filterStatus === "published"
                      ? "Đã đăng"
                      : "Đã loại trừ"
                  }".`}
            </div>
          ) : (
            <table className="w-full text-left text-sm text-slate-700">
              <thead className="border-b border-slate-100 bg-slate-50 text-xs uppercase text-slate-500">
                <tr>
                  <th className="w-10 px-3 py-3 text-center">
                    <input
                      type="checkbox"
                      checked={allSelected}
                      ref={(input) => {
                        if (input) input.indeterminate = isIndeterminate;
                      }}
                      onChange={handleToggleSelectAll}
                      className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                      title="Chọn tất cả video"
                    />
                  </th>
                  <th className="px-3 py-3 w-16">Video</th>
                  <th className="px-4 py-3">Tiêu đề / Caption</th>
                  <th className="px-4 py-3 whitespace-nowrap">Thời lượng</th>
                  <th className="px-4 py-3 whitespace-nowrap">Lượt xem</th>
                  <th className="px-4 py-3 whitespace-nowrap">Trạng thái</th>
                  <th className="px-4 py-3 text-right whitespace-nowrap">Thao tác</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filteredInventory.map((reel) => {
                  const isSelected = selectedIds.includes(reel.id);
                  const isProcessing = reel.status === "processing";
                  const isExcluded = reel.status === "excluded";
                  const isItemBusy = actionJobId === reel.id;

                  return (
                    <tr
                      key={reel.id}
                      className={`transition ${
                        isSelected ? "bg-indigo-50/50 hover:bg-indigo-50" : "hover:bg-slate-50/60"
                      }`}
                    >
                      {/* Checkbox */}
                      <td className="px-3 py-3 text-center">
                        <input
                          type="checkbox"
                          disabled={isProcessing}
                          checked={isSelected}
                          onChange={() => handleToggleSelectOne(reel.id)}
                          className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 cursor-pointer disabled:cursor-not-allowed disabled:opacity-40"
                        />
                      </td>

                      {/* Thumbnail */}
                      <td className="px-3 py-3">
                        {reel.thumbnail_url ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img
                            src={reel.thumbnail_url}
                            alt=""
                            className="h-12 w-9 rounded object-cover shadow-sm bg-slate-100"
                          />
                        ) : (
                          <div className="h-12 w-9 rounded bg-slate-100 flex items-center justify-center text-slate-400">
                            <IconVideo size={16} />
                          </div>
                        )}
                      </td>

                      {/* Caption / ID */}
                      <td className="px-4 py-3 max-w-sm">
                        <p
                          className="font-semibold text-slate-900 truncate text-xs sm:text-sm"
                          title={reel.caption || ""}
                        >
                          {reel.caption || "TikTok Video"}
                        </p>
                        <div className="flex items-center gap-2 mt-0.5">
                          <span className="text-[11px] text-slate-400">ID: {reel.reel_id}</span>
                          {reel.reel_url && (
                            <a
                              href={reel.reel_url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-[11px] text-indigo-600 hover:underline"
                            >
                              Xem TikTok ↗
                            </a>
                          )}
                        </div>
                      </td>

                      {/* Duration */}
                      <td className="px-4 py-3 text-xs text-slate-600 whitespace-nowrap">
                        {formatDuration(reel.duration)}
                      </td>

                      {/* Plays */}
                      <td className="px-4 py-3 text-xs text-slate-600 whitespace-nowrap">
                        {reel.play_count ? Number(reel.play_count).toLocaleString() : "—"}
                      </td>

                      {/* Status */}
                      <td className="px-4 py-3 whitespace-nowrap">
                        {reel.status === "published" ? (
                          <Badge tone="green" dot>
                            Đã đăng
                          </Badge>
                        ) : reel.status === "queued" ? (
                          <Badge tone="amber" dot>
                            Chờ đăng
                          </Badge>
                        ) : reel.status === "processing" ? (
                          <Badge tone="indigo" dot>
                            Đang đăng...
                          </Badge>
                        ) : isExcluded ? (
                          <Badge tone="rose">
                            Đã loại trừ
                          </Badge>
                        ) : (
                          <Badge tone="slate">Trong kho</Badge>
                        )}
                      </td>

                      {/* Action Column */}
                      <td className="px-4 py-3 text-right whitespace-nowrap">
                        {isExcluded ? (
                          <button
                            type="button"
                            disabled={actionLoading}
                            onClick={() => handleRestoreReel(reel.id)}
                            className="inline-flex min-h-[32px] items-center gap-1 rounded-lg border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-bold text-emerald-700 hover:bg-emerald-100 transition disabled:opacity-50"
                            title="Khôi phục video trở lại kho"
                          >
                            {isItemBusy ? <Spinner size={12} /> : <IconCheck size={12} />}
                            <span>Khôi phục</span>
                          </button>
                        ) : isProcessing ? (
                          <span className="text-xs text-slate-400 italic">Đang xử lý</span>
                        ) : (
                          <button
                            type="button"
                            disabled={actionLoading}
                            onClick={() => handleRequestDelete(reel)}
                            className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-400 hover:border-rose-300 hover:bg-rose-50 hover:text-rose-600 transition shadow-sm"
                            title="Loại bỏ video khỏi kho"
                          >
                            {isItemBusy ? <Spinner size={12} /> : <IconX size={15} />}
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </Card>

      {/* Confirmation Modal Dialog */}
      {confirmModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-sm p-4 animate-fadeIn">
          <div className="w-full max-w-md rounded-2xl bg-white p-5 shadow-2xl border border-slate-200">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-rose-100 text-rose-600">
                <IconTrash size={20} />
              </div>
              <div>
                <h3 className="text-sm font-extrabold text-slate-900">
                  {confirmModal.type === "single"
                    ? "Xác nhận loại bỏ video"
                    : `Xác nhận loại bỏ ${confirmModal.ids?.length} video`}
                </h3>
                <p className="mt-0.5 text-xs text-slate-500">
                  Thao tác này sẽ loại video khỏi danh sách xuất bản tự động.
                </p>
              </div>
            </div>

            <div className="mt-4 rounded-xl bg-slate-50 p-3.5 text-xs text-slate-600 leading-relaxed border border-slate-200/80">
              {confirmModal.type === "single" ? (
                <>
                  Bạn có chắc chắn muốn loại bỏ video:
                  <p className="mt-1 font-bold text-slate-900 line-clamp-2">
                    &quot;{confirmModal.reel?.caption || confirmModal.reel?.reel_id}&quot;
                  </p>
                  <p className="mt-2 text-[11px] text-slate-500">
                    Video sẽ được chuyển sang trạng thái <b>Đã loại trừ (Excluded)</b>, không được đưa vào
                    hàng đợi và không tự động đăng lên YouTube. Bạn có thể khôi phục lại bất kỳ lúc nào.
                  </p>
                </>
              ) : (
                <>
                  Bạn có chắc chắn muốn loại bỏ <b>{confirmModal.ids?.length} video</b> đã chọn khỏi kho?
                  <p className="mt-2 text-[11px] text-slate-500">
                    Các video này sẽ được chuyển sang trạng thái <b>Đã loại trừ (Excluded)</b>, không được
                    hệ thống tự động đăng lên YouTube và không bị quét thêm lại. Bạn vẫn có thể khôi phục sau.
                  </p>
                </>
              )}
            </div>

            <div className="flex items-center justify-end gap-2.5 pt-4 mt-2 border-t border-slate-100">
              <button
                type="button"
                disabled={actionLoading}
                onClick={() => setConfirmModal(null)}
                className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
              >
                Hủy
              </button>
              <button
                type="button"
                disabled={actionLoading}
                onClick={() => {
                  if (confirmModal.type === "single" && confirmModal.reel) {
                    void executeSingleDelete(confirmModal.reel.id);
                  } else if (confirmModal.type === "bulk" && confirmModal.ids) {
                    void executeBulkDelete(confirmModal.ids);
                  }
                }}
                className="inline-flex min-h-[38px] items-center gap-1.5 rounded-xl bg-rose-600 px-4 py-2 text-xs font-bold text-white shadow-sm hover:bg-rose-700 transition disabled:opacity-50"
              >
                {actionLoading ? <Spinner size={14} /> : <IconTrash size={14} />}
                <span>
                  {confirmModal.type === "single"
                    ? "Xóa khỏi kho"
                    : `Xóa ${confirmModal.ids?.length} video`}
                </span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
