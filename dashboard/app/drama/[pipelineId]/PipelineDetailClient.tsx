"use client";

import { useState, useTransition } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Card,
  CardHeader,
  StatCard,
  Badge,
  Spinner,
  EmptyState,
  btnPrimary,
  btnSecondary,
  btnSmall,
  inputCls,
  labelCls,
} from "@/components/ui";
import {
  IconBack,
  IconSources,
  IconFilm,
  IconPlay,
  IconRefresh,
  IconPlus,
  IconCheck,
  IconAlert,
  IconX,
  IconClock,
} from "@/components/icons";
import type {
  DramaPipelineDto,
  DramaSummaryDto,
  DramaSourceDto,
  DramaSeriesDto,
  DramaEpisodeDto,
  DramaPipelineInventoryDto,
} from "@/lib/drama-api";

export type DramaTabKey = "overview" | "sources" | "series" | "inventory";

const TABS: { key: DramaTabKey; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "sources", label: "Sources" },
  { key: "series", label: "Series" },
  { key: "inventory", label: "Inventory" },
];

const REGISTERED_PROVIDERS = [
  { id: "rapidix", name: "RapidIX (ReelShort)" },
  { id: "starshort", name: "StarShort" },
  { id: "dramabox", name: "DramaBox" },
  { id: "flickshort", name: "FlickShort" },
  { id: "netshort", name: "NetShort" },
  { id: "shortmax", name: "ShortMax" },
  { id: "reelshort_sdp", name: "ReelShort SDP" },
];

function formatDuration(sec: number | null | undefined): string {
  if (sec == null || isNaN(sec) || sec <= 0) return "—";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s < 10 ? "0" : ""}${s}`;
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "—";
    return d.toLocaleString("vi-VN", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "—";
  }
}

function episodeStatusTone(status: string): string {
  switch (status.toLowerCase()) {
    case "published":
      return "green";
    case "processing":
    case "queued":
      return "amber";
    case "failed":
      return "red";
    case "skipped":
      return "slate";
    default:
      return "blue";
  }
}

// ---------- Create Source Modal ----------

function CreateSourceModal({
  pipelineId,
  onClose,
  onCreated,
}: {
  pipelineId: string;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [provider, setProvider] = useState("rapidix");
  const [sourceUrl, setSourceUrl] = useState("");
  const [extId, setExtId] = useState("");
  const [name, setName] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isSubmitting) return;
    setIsSubmitting(true);
    setErrorMsg(null);

    try {
      const res = await fetch(`/api/drama/pipelines/${encodeURIComponent(pipelineId)}/sources`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: provider.trim(),
          source_url: sourceUrl.trim() || null,
          external_series_id: extId.trim() || null,
          name: name.trim() || null,
          enabled,
        }),
      });

      if (!res.ok) {
        let msg = "Lỗi khi tạo source";
        try {
          const d = await res.json();
          if (d.error) msg = d.error;
          else if (d.message) msg = d.message;
        } catch {
          // ignore
        }
        throw new Error(msg);
      }

      onCreated();
      onClose();
    } catch (err: any) {
      setErrorMsg(err.message || "Không thể tạo source.");
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm sm:p-6">
      <div className="w-full max-w-lg rounded-3xl bg-white p-6 shadow-2xl sm:p-8">
        <div className="flex items-center justify-between border-b border-slate-100 pb-4">
          <div>
            <h3 className="text-lg font-extrabold text-slate-900 sm:text-xl">
              Thêm Nguồn Drama (Source)
            </h3>
            <p className="mt-1 text-xs text-slate-500">
              Cấu hình nguồn quét phim cho pipeline này
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          >
            <IconX size={18} />
          </button>
        </div>

        {errorMsg && (
          <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-3.5 text-xs font-semibold text-rose-700">
            {errorMsg}
          </div>
        )}

        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <div>
            <label className={labelCls}>Nhà cung cấp (Provider) *</label>
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              className={inputCls}
            >
              {REGISTERED_PROVIDERS.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className={labelCls}>Tên nguồn (Ghi nhớ)</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="VD: Kho Phim Ngắn Tổng Hợp"
              className={inputCls}
            />
          </div>

          <div>
            <label className={labelCls}>External Series ID (Nếu có)</label>
            <input
              type="text"
              value={extId}
              onChange={(e) => setExtId(e.target.value)}
              placeholder="VD: 10001"
              className={inputCls}
            />
          </div>

          <div>
            <label className={labelCls}>Source URL (Nếu có)</label>
            <input
              type="url"
              value={sourceUrl}
              onChange={(e) => setSourceUrl(e.target.value)}
              placeholder="https://..."
              className={inputCls}
            />
          </div>

          <div className="flex items-center gap-2 pt-1">
            <label className="flex cursor-pointer items-center gap-2 text-xs font-semibold text-slate-700">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
                className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-600"
              />
              Kích hoạt ngay (Enabled)
            </label>
          </div>

          <div className="mt-6 flex gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              className={`${btnSecondary} flex-1`}
            >
              Hủy
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className={`${btnPrimary} flex-1`}
            >
              {isSubmitting ? <Spinner size={16} /> : "Thêm Nguồn"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------- Series Detail & Episodes Modal ----------

function SeriesEpisodesModal({
  series,
  onClose,
}: {
  series: DramaSeriesDto;
  onClose: () => void;
}) {
  const [episodes, setEpisodes] = useState<DramaEpisodeDto[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useState(() => {
    let cancelled = false;
    fetch(`/api/drama/series/${encodeURIComponent(series.id)}/episodes?limit=500`)
      .then((res) => {
        if (!res.ok) throw new Error("Không thể tải danh sách tập");
        return res.json();
      })
      .then((data) => {
        if (cancelled) return;
        const list = Array.isArray(data.items) ? data.items : [];
        // Strictly numerical sort episode_number ASC
        list.sort((a: DramaEpisodeDto, b: DramaEpisodeDto) => (Number(a.episode_number) || 0) - (Number(b.episode_number) || 0));
        setEpisodes(list);
        setLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err.message || "Lỗi tải tập phim");
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm sm:p-6">
      <div className="flex max-h-[90vh] w-full max-w-2xl flex-col rounded-3xl bg-white shadow-2xl">
        {/* Header */}
        <div className="flex items-start justify-between border-b border-slate-100 p-5 sm:p-6">
          <div className="flex items-center gap-3.5">
            <div className="relative h-14 w-10 shrink-0 overflow-hidden rounded-lg bg-slate-100">
              {series.thumbnail_url ? (
                <img
                  src={series.thumbnail_url}
                  alt={series.title || "Series"}
                  className="h-full w-full object-cover"
                />
              ) : (
                <div className="flex h-full w-full items-center justify-center text-slate-300">
                  <IconFilm size={18} />
                </div>
              )}
            </div>
            <div>
              <h3 className="line-clamp-1 text-base font-extrabold text-slate-900 sm:text-lg">
                {series.title || "Chưa có tiêu đề"}
              </h3>
              <p className="mt-0.5 text-xs text-slate-500">
                Mã: <span className="font-mono">{series.external_series_id}</span> • Tổng:{" "}
                <span className="font-bold text-slate-700">
                  {series.total_episodes != null ? `${series.total_episodes} tập` : `${episodes.length} tập`}
                </span>
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          >
            <IconX size={18} />
          </button>
        </div>

        {/* Content list */}
        <div className="flex-1 overflow-y-auto p-5 sm:p-6">
          {loading ? (
            <div className="flex justify-center py-12">
              <Spinner size={32} />
            </div>
          ) : error ? (
            <div className="rounded-xl bg-rose-50 p-4 text-xs font-semibold text-rose-700">
              {error}
            </div>
          ) : episodes.length === 0 ? (
            <EmptyState
              title="Chưa có tập phim nào"
              hint="Nguồn chưa quét tập cho bộ phim này."
              icon={<IconPlay size={24} />}
            />
          ) : (
            <div className="divide-y divide-slate-100">
              {episodes.map((ep) => (
                <div
                  key={ep.id}
                  className="flex items-center justify-between gap-3 py-3 hover:bg-slate-50/80 rounded-lg px-2"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="inline-flex h-7 w-9 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-xs font-bold text-indigo-700">
                      #{ep.episode_number}
                    </span>
                    <div className="min-w-0">
                      <p className="truncate text-xs font-bold text-slate-900">
                        {ep.title ? ep.title : `Tập ${ep.episode_number}`}
                      </p>
                      <p className="text-[11px] text-slate-400">
                        Thời lượng: {formatDuration(ep.duration)}
                      </p>
                    </div>
                  </div>
                  <Badge tone={episodeStatusTone(ep.status)}>
                    {ep.status}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="border-t border-slate-100 p-4 text-right">
          <button type="button" onClick={onClose} className={btnSecondary}>
            Đóng
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------- Main Detail Client Component ----------

export function PipelineDetailClient({
  pipeline,
  initialSummary,
  summaryError,
  initialSources,
  sourcesError,
  initialSeries,
  seriesError,
  initialInventory,
  inventoryError,
  initialTab,
}: {
  pipeline: DramaPipelineDto;
  initialSummary: DramaSummaryDto;
  summaryError: string | null;
  initialSources: DramaSourceDto[];
  sourcesError: string | null;
  initialSeries: DramaSeriesDto[];
  seriesError: string | null;
  initialInventory: DramaPipelineInventoryDto;
  inventoryError: string | null;
  initialTab: DramaTabKey;
}) {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState<DramaTabKey>(initialTab);
  const [summary, setSummary] = useState<DramaSummaryDto>(initialSummary);
  const [sources, setSources] = useState<DramaSourceDto[]>(initialSources);
  const [series, setSeries] = useState<DramaSeriesDto[]>(initialSeries);
  const [inventory, setInventory] = useState<DramaPipelineInventoryDto>(initialInventory);

  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [scanningSourceId, setScanningSourceId] = useState<string | null>(null);
  const [scanMessage, setScanMessage] = useState<{
    tone: "green" | "red";
    text: string;
  } | null>(null);

  const [selectedSeries, setSelectedSeries] = useState<DramaSeriesDto | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [searchInventoryQuery, setSearchInventoryQuery] = useState("");

  const refreshAllData = async () => {
    try {
      const [sumRes, srcRes, serRes, invRes] = await Promise.all([
        fetch(`/api/drama/pipelines/${encodeURIComponent(pipeline.id)}/summary`),
        fetch(`/api/drama/pipelines/${encodeURIComponent(pipeline.id)}/sources`),
        fetch(`/api/drama/pipelines/${encodeURIComponent(pipeline.id)}/series`),
        fetch(`/api/drama/pipelines/${encodeURIComponent(pipeline.id)}/inventory?limit=500`),
      ]);

      if (sumRes.ok) setSummary(await sumRes.json());
      if (srcRes.ok) setSources(await srcRes.json());
      if (serRes.ok) setSeries(await serRes.json());
      if (invRes.ok) setInventory(await invRes.json());
    } catch {
      // ignore
    }
  };

  const handleTabChange = (key: DramaTabKey) => {
    setActiveTab(key);
    // Smooth URL change without full reload
    window.history.replaceState(null, "", `/drama/${encodeURIComponent(pipeline.id)}?tab=${key}`);
  };

  const handleScanSource = async (sourceId: string) => {
    if (scanningSourceId) return;
    setScanningSourceId(sourceId);
    setScanMessage(null);

    try {
      const res = await fetch(`/api/drama/sources/${encodeURIComponent(sourceId)}/scan`, {
        method: "POST",
      });

      if (!res.ok) {
        let msg = "Quét nguồn thất bại";
        try {
          const d = await res.json();
          if (d.error) msg = d.error;
          else if (d.message) msg = d.message;
        } catch {
          // ignore
        }
        setScanMessage({ tone: "red", text: `Lỗi quét: ${msg}` });
      } else {
        const data = await res.json();
        setScanMessage({
          tone: "green",
          text: `Quét thành công! Tìm thấy ${data.series_found ?? 0} bộ phim và ${data.episodes_found ?? 0} tập.`,
        });
        await refreshAllData();
      }
    } catch (err: any) {
      setScanMessage({ tone: "red", text: `Lỗi kết nối: ${err.message}` });
    } finally {
      setScanningSourceId(null);
    }
  };

  // Filter and numerically sort inventory episodes
  const sortedInventoryItems = [...inventory.items]
    .filter((ep) => {
      if (statusFilter && ep.status.toLowerCase() !== statusFilter.toLowerCase()) {
        return false;
      }
      if (searchInventoryQuery.trim()) {
        const q = searchInventoryQuery.trim().toLowerCase();
        const matchTitle = (ep.title || "").toLowerCase().includes(q);
        const matchNum = String(ep.episode_number).includes(q);
        return matchTitle || matchNum;
      }
      return true;
    })
    .sort((a, b) => (Number(a.episode_number) || 0) - (Number(b.episode_number) || 0));

  return (
    <div className="w-full min-w-0">
      {/* Header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2.5">
            <h1 className="truncate text-xl font-extrabold tracking-tight text-slate-900 sm:text-2xl">
              {pipeline.name}
            </h1>
            {pipeline.enabled ? (
              <Badge tone="green" dot>
                Enabled
              </Badge>
            ) : (
              <Badge tone="slate">Disabled</Badge>
            )}
          </div>
          <p className="mt-1 font-mono text-xs text-slate-500 sm:text-sm">
            /{pipeline.slug}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Link
            href="/drama"
            className="inline-flex min-h-[44px] shrink-0 items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 sm:min-h-[38px]"
          >
            <IconBack size={15} />
            Drama
          </Link>
        </div>
      </div>

      {/* Sticky Tab Navigation Bar */}
      <div className="sticky top-14 z-30 -mx-4 mt-4 px-4 sm:-mx-6 sm:px-6">
        <nav
          aria-label="Drama pipeline tabs"
          className="mx-auto flex max-w-7xl gap-1 overflow-x-auto rounded-2xl border border-slate-200/90 bg-white/95 p-1.5 shadow-[0_1px_2px_rgba(15,23,42,0.06)] backdrop-blur"
        >
          {TABS.map((t) => {
            const active = activeTab === t.key;
            return (
              <button
                key={t.key}
                type="button"
                onClick={() => handleTabChange(t.key)}
                className={`inline-flex min-h-[44px] shrink-0 items-center gap-1.5 rounded-xl px-4 py-2 text-[13px] font-bold transition sm:min-h-[38px] ${
                  active
                    ? "bg-indigo-600 text-white shadow-[0_4px_12px_-4px_rgba(79,70,229,0.7)]"
                    : "text-slate-500 hover:bg-slate-100 hover:text-slate-900"
                }`}
              >
                {t.label}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Global Scan Notification */}
      {scanMessage && (
        <div
          className={`mt-4 flex items-center justify-between rounded-2xl p-4 text-xs font-semibold ${
            scanMessage.tone === "green"
              ? "border border-emerald-200 bg-emerald-50 text-emerald-800"
              : "border border-rose-200 bg-rose-50 text-rose-800"
          }`}
        >
          <div className="flex items-center gap-2">
            {scanMessage.tone === "green" ? (
              <IconCheck size={16} className="text-emerald-600" />
            ) : (
              <IconAlert size={16} className="text-rose-600" />
            )}
            <span>{scanMessage.text}</span>
          </div>
          <button
            type="button"
            onClick={() => setScanMessage(null)}
            className="rounded-lg p-1 text-slate-400 hover:bg-slate-200/60 hover:text-slate-700"
          >
            <IconX size={14} />
          </button>
        </div>
      )}

      {/* Tab Contents */}
      <div className="mt-4">
        {/* ===================== TAB: OVERVIEW ===================== */}
        {activeTab === "overview" && (
          <div className="space-y-6">
            {summaryError && (
              <div className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-xs text-rose-700">
                Lỗi tải summary: {summaryError}
              </div>
            )}

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <StatCard
                label="Sources"
                value={summary.sources}
                icon={<IconSources size={18} />}
                accent="indigo"
                sub="Nguồn dữ liệu đã gắn"
              />
              <StatCard
                label="Series"
                value={summary.series}
                icon={<IconFilm size={18} />}
                accent="emerald"
                sub="Bộ phim đã quét"
              />
              <StatCard
                label="Episodes"
                value={summary.inventory}
                icon={<IconPlay size={18} />}
                accent="amber"
                sub="Tổng tập trong kho"
              />
            </div>

            <Card>
              <CardHeader
                title="Thông Tin Pipeline"
                subtitle="Cấu hình hệ thống lưu trữ và trạng thái"
              />
              <div className="divide-y divide-slate-100 px-4 py-2 sm:px-6 text-sm">
                <div className="flex items-center justify-between py-3">
                  <span className="text-slate-500">Pipeline ID</span>
                  <span className="font-mono text-xs font-semibold text-slate-800">
                    {pipeline.id}
                  </span>
                </div>
                <div className="flex items-center justify-between py-3">
                  <span className="text-slate-500">Đường dẫn tĩnh (Slug)</span>
                  <span className="font-mono text-xs font-semibold text-slate-800">
                    /{pipeline.slug}
                  </span>
                </div>
                <div className="flex items-center justify-between py-3">
                  <span className="text-slate-500">Trạng thái</span>
                  <Badge tone={pipeline.enabled ? "green" : "slate"}>
                    {pipeline.enabled ? "Đang hoạt động" : "Tạm dừng"}
                  </Badge>
                </div>
                <div className="flex items-center justify-between py-3">
                  <span className="text-slate-500">Ngày tạo</span>
                  <span className="text-xs text-slate-700">
                    {formatDate(pipeline.created_at)}
                  </span>
                </div>
                <div className="flex items-center justify-between py-3">
                  <span className="text-slate-500">Cập nhật lần cuối</span>
                  <span className="text-xs text-slate-700">
                    {formatDate(pipeline.updated_at)}
                  </span>
                </div>
              </div>
            </Card>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="rounded-2xl border border-slate-200/90 bg-white p-5 shadow-sm">
                <h4 className="text-sm font-extrabold text-slate-900">
                  Thao tác nhanh Nguồn (Sources)
                </h4>
                <p className="mt-1 text-xs text-slate-500">
                  Thêm nguồn mới từ RapidIX, DramaBox, ShortMax hoặc quét dữ liệu mới.
                </p>
                <div className="mt-4 flex gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      setCreateModalOpen(true);
                    }}
                    className={btnSmall}
                  >
                    <IconPlus size={14} className="mr-1" />
                    Thêm Nguồn
                  </button>
                  <button
                    type="button"
                    onClick={() => handleTabChange("sources")}
                    className={btnSecondary}
                  >
                    Xem Nguồn ({sources.length})
                  </button>
                </div>
              </div>

              <div className="rounded-2xl border border-slate-200/90 bg-white p-5 shadow-sm">
                <h4 className="text-sm font-extrabold text-slate-900">
                  Kho tập phim (Inventory)
                </h4>
                <p className="mt-1 text-xs text-slate-500">
                  Kiểm tra toàn bộ danh sách các tập phim đã được nhập vào hệ thống.
                </p>
                <div className="mt-4 flex gap-2">
                  <button
                    type="button"
                    onClick={() => handleTabChange("inventory")}
                    className={btnPrimary}
                  >
                    Xem Kho Phim ({summary.inventory})
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ===================== TAB: SOURCES ===================== */}
        {activeTab === "sources" && (
          <div className="space-y-4">
            {sourcesError && (
              <div className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-xs text-rose-700">
                Lỗi tải sources: {sourcesError}
              </div>
            )}

            <Card>
              <CardHeader
                title="Nguồn Dữ Liệu (Sources)"
                subtitle="Danh sách các nhà cung cấp kết nối vào pipeline này"
                action={
                  <button
                    type="button"
                    onClick={() => setCreateModalOpen(true)}
                    className={btnPrimary}
                  >
                    <IconPlus size={14} className="mr-1" />
                    Thêm Nguồn
                  </button>
                }
              />

              {sources.length === 0 ? (
                <EmptyState
                  title="Chưa có nguồn dữ liệu nào"
                  hint="Hãy thêm nguồn đầu tiên từ RapidIX, ShortMax, v.v. để bắt đầu quét phim."
                  action={
                    <button
                      type="button"
                      onClick={() => setCreateModalOpen(true)}
                      className={btnPrimary}
                    >
                      <IconPlus size={14} className="mr-1" />
                      Thêm Nguồn Ngay
                    </button>
                  }
                  icon={<IconSources size={24} />}
                />
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs sm:text-sm text-slate-600">
                    <thead className="bg-slate-50 text-[11px] font-bold uppercase tracking-wider text-slate-500">
                      <tr>
                        <th className="px-4 py-3 sm:px-6">Tên / Mã</th>
                        <th className="px-4 py-3">Provider</th>
                        <th className="px-4 py-3">Trạng thái</th>
                        <th className="px-4 py-3">Scan Gần Nhất</th>
                        <th className="px-4 py-3 text-right sm:px-6">Thao tác</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {sources.map((src) => {
                        const isScanning = scanningSourceId === src.id;
                        return (
                          <tr key={src.id} className="hover:bg-slate-50/70 transition">
                            <td className="px-4 py-3.5 sm:px-6 font-medium text-slate-900">
                              <div className="font-bold">
                                {src.name || src.external_series_id || "Không tên"}
                              </div>
                              {src.external_series_id && (
                                <div className="font-mono text-[11px] text-slate-400">
                                  ID: {src.external_series_id}
                                </div>
                              )}
                              {src.last_scan_error && (
                                <div className="mt-1 text-[11px] text-rose-600 line-clamp-1">
                                  Lỗi: {src.last_scan_error}
                                </div>
                              )}
                            </td>
                            <td className="px-4 py-3.5">
                              <Badge tone="indigo">{src.provider}</Badge>
                            </td>
                            <td className="px-4 py-3.5">
                              <Badge tone={src.enabled ? "green" : "slate"}>
                                {src.enabled ? "Enabled" : "Disabled"}
                              </Badge>
                            </td>
                            <td className="px-4 py-3.5 text-xs text-slate-500">
                              <div>{formatDate(src.last_scan_at)}</div>
                              {src.last_scan_status && (
                                <span className="text-[10px] uppercase font-bold text-slate-400">
                                  {src.last_scan_status}
                                </span>
                              )}
                            </td>
                            <td className="px-4 py-3.5 text-right sm:px-6">
                              <button
                                type="button"
                                onClick={() => handleScanSource(src.id)}
                                disabled={isScanning}
                                className={btnSmall}
                              >
                                {isScanning ? (
                                  <Spinner size={14} />
                                ) : (
                                  <IconRefresh size={14} className="mr-1" />
                                )}
                                Scan now
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          </div>
        )}

        {/* ===================== TAB: SERIES ===================== */}
        {activeTab === "series" && (
          <div className="space-y-4">
            {seriesError && (
              <div className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-xs text-rose-700">
                Lỗi tải series: {seriesError}
              </div>
            )}

            <Card>
              <CardHeader
                title="Danh Sách Phim (Series)"
                subtitle={`Tổng cộng: ${series.length} bộ phim trong pipeline này`}
              />

              {series.length === 0 ? (
                <EmptyState
                  title="Chưa có bộ phim nào"
                  hint="Hãy vào tab Sources và bấm 'Scan now' để nạp phim vào pipeline."
                  icon={<IconFilm size={24} />}
                />
              ) : (
                <div className="grid grid-cols-2 gap-3.5 p-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 sm:p-6">
                  {series.map((item) => (
                    <div
                      key={item.id}
                      onClick={() => setSelectedSeries(item)}
                      className="group flex cursor-pointer flex-col overflow-hidden rounded-2xl border border-slate-200/90 bg-white shadow-sm transition hover:border-indigo-300 hover:shadow-md"
                    >
                      <div className="relative aspect-[3/4] w-full overflow-hidden bg-slate-100">
                        {item.thumbnail_url ? (
                          <img
                            src={item.thumbnail_url}
                            alt={item.title || "Poster"}
                            className="h-full w-full object-cover transition duration-300 group-hover:scale-105"
                          />
                        ) : (
                          <div className="flex h-full w-full items-center justify-center text-slate-300">
                            <IconFilm size={28} />
                          </div>
                        )}
                        <div className="absolute right-2 top-2">
                          <Badge tone="green">
                            {item.total_episodes != null
                              ? `${item.total_episodes} Tập`
                              : "Đầy đủ"}
                          </Badge>
                        </div>
                      </div>
                      <div className="flex flex-1 flex-col p-3">
                        <h4 className="line-clamp-2 text-xs font-bold text-slate-900 group-hover:text-indigo-600 sm:text-sm">
                          {item.title || "Chưa có tiêu đề"}
                        </h4>
                        <div className="mt-auto pt-2 flex items-center justify-between text-[11px] text-slate-400">
                          <span className="font-mono">
                            {item.external_series_id || item.id.slice(0, 8)}
                          </span>
                          <span className="text-indigo-600 font-semibold group-hover:underline">
                            Xem tập →
                          </span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </div>
        )}

        {/* ===================== TAB: INVENTORY ===================== */}
        {activeTab === "inventory" && (
          <div className="space-y-4">
            {inventoryError && (
              <div className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-xs text-rose-700">
                Lỗi tải inventory: {inventoryError}
              </div>
            )}

            <Card>
              <CardHeader
                title="Kho Tập Phim (Inventory)"
                subtitle={`Hiển thị ${sortedInventoryItems.length} / ${inventory.items.length} tập phim (sắp xếp tăng dần theo tập)`}
              />

              {/* Filters & Search */}
              <div className="flex flex-col gap-3 border-b border-slate-100 p-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
                <div className="flex flex-wrap items-center gap-2">
                  {["", "new", "queued", "processing", "published", "failed"].map((st) => (
                    <button
                      key={st}
                      type="button"
                      onClick={() => setStatusFilter(st)}
                      className={`rounded-xl px-3 py-1.5 text-xs font-semibold transition ${
                        statusFilter === st
                          ? "bg-indigo-600 text-white"
                          : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                      }`}
                    >
                      {st ? st.toUpperCase() : "TẤT CẢ"}
                    </button>
                  ))}
                </div>

                <div className="w-full sm:w-64">
                  <input
                    type="text"
                    value={searchInventoryQuery}
                    onChange={(e) => setSearchInventoryQuery(e.target.value)}
                    placeholder="Tìm theo tập hoặc tên..."
                    className={inputCls}
                  />
                </div>
              </div>

              {sortedInventoryItems.length === 0 ? (
                <EmptyState
                  title="Không tìm thấy tập phim nào"
                  hint="Thử thay đổi bộ lọc hoặc quét thêm nguồn dữ liệu."
                  icon={<IconPlay size={24} />}
                />
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs sm:text-sm text-slate-600">
                    <thead className="bg-slate-50 text-[11px] font-bold uppercase tracking-wider text-slate-500">
                      <tr>
                        <th className="px-4 py-3 sm:px-6">Tập</th>
                        <th className="px-4 py-3">Tiêu đề</th>
                        <th className="px-4 py-3">Thời lượng</th>
                        <th className="px-4 py-3">Trạng thái</th>
                        <th className="px-4 py-3 text-right sm:px-6">Ngày cập nhật</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {sortedInventoryItems.map((ep) => (
                        <tr key={ep.id} className="hover:bg-slate-50/70 transition">
                          <td className="px-4 py-3.5 sm:px-6">
                            <span className="inline-flex h-7 min-w-8 items-center justify-center rounded-lg bg-indigo-50 px-2 text-xs font-extrabold text-indigo-700">
                              #{ep.episode_number}
                            </span>
                          </td>
                          <td className="px-4 py-3.5 font-medium text-slate-900">
                            <div className="line-clamp-1">{ep.title || `Tập ${ep.episode_number}`}</div>
                            {ep.external_episode_id && (
                              <div className="font-mono text-[10px] text-slate-400">
                                {ep.external_episode_id}
                              </div>
                            )}
                          </td>
                          <td className="px-4 py-3.5 text-xs text-slate-500">
                            <div className="flex items-center gap-1">
                              <IconClock size={12} className="text-slate-400" />
                              {formatDuration(ep.duration)}
                            </div>
                          </td>
                          <td className="px-4 py-3.5">
                            <Badge tone={episodeStatusTone(ep.status)}>
                              {ep.status}
                            </Badge>
                          </td>
                          <td className="px-4 py-3.5 text-right sm:px-6 text-xs text-slate-400">
                            {formatDate(ep.updated_at || ep.created_at)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          </div>
        )}
      </div>

      {/* Create Source Modal */}
      {createModalOpen && (
        <CreateSourceModal
          pipelineId={pipeline.id}
          onClose={() => setCreateModalOpen(false)}
          onCreated={refreshAllData}
        />
      )}

      {/* Series Episodes Modal */}
      {selectedSeries && (
        <SeriesEpisodesModal
          series={selectedSeries}
          onClose={() => setSelectedSeries(null)}
        />
      )}
    </div>
  );
}
