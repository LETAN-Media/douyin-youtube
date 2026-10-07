"use client";

import Link from "next/link";
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import {
  PageHeader,
  StatCard,
  backLinkCls,
  btnPrimary,
  btnSecondary,
  btnSmall,
  btnDanger,
  inputCls,
  labelCls,
  EmptyState,
} from "@/components/ui";
import { IconChevronRight, IconPlus, IconRefresh, IconFilm } from "@/components/icons";
import type {
  DramaPipelineDto,
  DramaSummaryDto,
  DramaSourceDto,
  DramaSeriesDto,
  DramaPipelineInventoryDto,
} from "@/lib/drama-api";

function CreateSourceModal({
  pipelineId,
  onClose,
}: {
  pipelineId: string;
  onClose: () => void;
}) {
  const router = useRouter();
  const [provider, setProvider] = useState("rapidix");
  const [sourceUrl, setSourceUrl] = useState("");
  const [extId, setExtId] = useState("");
  const [name, setName] = useState("");
  const [isPending, startTransition] = useTransition();
  const [isCreating, setIsCreating] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isCreating || isPending) return;
    setIsCreating(true);
    setErrorMsg("");

    try {
      const res = await fetch(`/api/drama/pipelines/${pipelineId}/sources`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider,
          source_url: sourceUrl || null,
          external_series_id: extId || null,
          name: name || null,
          enabled: true,
        }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.error || "Lỗi tạo source");
      }
      onClose();
      startTransition(() => {
        router.refresh();
      });
    } catch (err: any) {
      setErrorMsg(err.message);
      setIsCreating(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-sm sm:p-6">
      <div className="w-full max-w-md rounded-3xl bg-white p-6 shadow-xl sm:p-8">
        <h3 className="text-xl font-extrabold text-slate-900">Thêm Source</h3>
        <p className="mt-1 text-sm text-slate-500">
          Thêm nguồn lấy dữ liệu cho pipeline.
        </p>
        {errorMsg && (
          <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm font-semibold text-rose-700">
            {errorMsg}
          </div>
        )}
        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <div>
            <label className={labelCls}>Provider *</label>
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              className={inputCls}
            >
              <option value="rapidix">RapidIX (ReelShort)</option>
              <option value="dramabox">DramaBox</option>
              <option value="shortmax">ShortMax</option>
            </select>
          </div>
          <div>
            <label className={labelCls}>Source URL / External ID</label>
            <input
              value={extId}
              onChange={(e) => setExtId(e.target.value)}
              placeholder="VD: series_12345"
              className={inputCls}
            />
          </div>
          <div>
            <label className={labelCls}>Tên (hiển thị)</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="VD: Phim ABC"
              className={inputCls}
            />
          </div>

          <div className="mt-6 flex gap-2">
            <button
              type="button"
              className={`${btnSecondary} flex-1`}
              onClick={onClose}
              disabled={isCreating || isPending}
            >
              Hủy
            </button>
            <button
              type="submit"
              className={`${btnPrimary} flex-1`}
              disabled={isCreating || isPending}
            >
              {isCreating || isPending ? "Đang thêm..." : "Thêm Source"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export function PipelineDetailClient({
  pipeline,
  summary,
  sources,
  series,
  inventory,
}: {
  pipeline: DramaPipelineDto;
  summary: DramaSummaryDto;
  sources: DramaSourceDto[];
  series: DramaSeriesDto[];
  inventory: DramaPipelineInventoryDto;
}) {
  const router = useRouter();
  const [createSourceOpen, setCreateSourceOpen] = useState(false);
  const [scanning, setScanning] = useState<string | null>(null);

  const handleScan = async (sourceId: string) => {
    if (scanning) return;
    setScanning(sourceId);
    try {
      const res = await fetch(`/api/drama/sources/${sourceId}/scan`, {
        method: "POST",
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        alert("Scan lỗi: " + (d.error || "Unknown"));
      } else {
        const data = await res.json();
        alert(`Scan thành công. Tìm thấy ${data.episodes_found} tập.`);
        router.refresh();
      }
    } catch (err: any) {
      alert("Lỗi gọi API: " + err.message);
    } finally {
      setScanning(null);
    }
  };

  return (
    <>
      <div className="mb-4">
        <Link href="/drama" className={backLinkCls}>
          <IconChevronRight size={16} />
          Trở lại danh sách
        </Link>
      </div>

      <PageHeader
        eyebrow="Pipeline Detail"
        title={pipeline.name}
        description={`Slug: ${pipeline.slug} • Trạng thái: ${pipeline.enabled ? "Hoạt động" : "Tạm dừng"}`}
      />

      <div className="mt-8 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Sources" value={summary.sources} />
        <StatCard label="Series" value={summary.series} />
        <StatCard label="Episodes" value={summary.inventory} />
      </div>

      <div className="mt-12 rounded-3xl border border-slate-200/90 bg-white shadow-sm overflow-hidden">
        <PageHeader
          title="Sources"
          description="Danh sách các nguồn quét phim"
          actions={
            <button className={btnSmall} onClick={() => setCreateSourceOpen(true)}>
              <IconPlus size={14} className="mr-1" />
              Thêm Source
            </button>
          }
        />
        <div className="p-0">
          {sources.length === 0 ? (
            <EmptyState title="Chưa có source nào" hint="Bấm thêm source để bắt đầu." />
          ) : (
            <div className="divide-y divide-slate-100 overflow-x-auto">
              <table className="w-full text-left text-sm text-slate-600">
                <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wider text-slate-500">
                  <tr>
                    <th className="px-5 py-3">Tên / Provider</th>
                    <th className="px-5 py-3">Scan Gần Nhất</th>
                    <th className="px-5 py-3 text-right">Thao tác</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {sources.map((src) => (
                    <tr key={src.id} className="hover:bg-slate-50">
                      <td className="px-5 py-4 font-medium text-slate-900">
                        {src.name || src.external_series_id || src.id}
                        <div className="text-xs text-slate-500 mt-1">{src.provider}</div>
                      </td>
                      <td className="px-5 py-4 text-xs">
                        {src.last_scan_at ? new Date(src.last_scan_at).toLocaleString('vi-VN') : "Chưa scan"}
                      </td>
                      <td className="px-5 py-4 text-right">
                        <button
                          onClick={() => handleScan(src.id)}
                          disabled={scanning === src.id}
                          className={btnSmall}
                        >
                          <IconRefresh size={14} className={`mr-1 ${scanning === src.id ? "animate-spin" : ""}`} />
                          Scan
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      <div className="mt-8 rounded-3xl border border-slate-200/90 bg-white shadow-sm overflow-hidden">
        <PageHeader title="Series & Episodes (Mới nhất)" />
        <div className="p-0">
          {inventory.items.length === 0 ? (
            <EmptyState title="Chưa có tập phim nào" icon={<IconFilm size={24} />} />
          ) : (
            <div className="divide-y divide-slate-100 overflow-x-auto">
              <table className="w-full text-left text-sm text-slate-600">
                <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wider text-slate-500">
                  <tr>
                    <th className="px-5 py-3">Tập</th>
                    <th className="px-5 py-3">Title</th>
                    <th className="px-5 py-3">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {inventory.items.map((ep) => (
                    <tr key={ep.id} className="hover:bg-slate-50">
                      <td className="px-5 py-4 font-medium text-slate-900">Tập {ep.episode_number}</td>
                      <td className="px-5 py-4">{ep.title || "---"}</td>
                      <td className="px-5 py-4">
                        <span className="inline-flex rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-semibold text-slate-800">
                          {ep.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {createSourceOpen && (
        <CreateSourceModal
          pipelineId={pipeline.id}
          onClose={() => setCreateSourceOpen(false)}
        />
      )}
    </>
  );
}
