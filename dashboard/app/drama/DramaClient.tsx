"use client";

import Link from "next/link";
import { useState, useTransition, useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  PageHeader,
  btnPrimary,
  btnSecondary,
  btnSmall,
  inputCls,
  labelCls,
  Spinner,
  Badge,
  EmptyState,
} from "@/components/ui";
import {
  IconChevronRight,
  IconFilm,
  IconPlus,
  IconX,
  IconCheck,
  IconAlert,
  IconPlay,
} from "@/components/icons";
import type {
  DramaPipelineDto,
  DramaSummaryDto,
  DramaDiscoverySeriesDto,
  DramaDiscoveryResponseDto,
  DramaProviderErrorDto,
  DramaProviderStatusDto,
} from "@/lib/drama-api";

function CreatePipelineModal({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [errorMsg, setErrorMsg] = useState("");
  const [isPending, startTransition] = useTransition();
  const [isCreating, setIsCreating] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isCreating || isPending) return;

    const trimmedName = name.trim();
    const trimmedSlug = slug.replace(/-/g, " ").trim().replace(/\s+/g, "-").toLowerCase();

    if (!trimmedName || trimmedName.length > 200) {
      setErrorMsg("Tên không hợp lệ (max 200 ký tự).");
      return;
    }

    setIsCreating(true);
    setErrorMsg("");

    try {
      const res = await fetch("/api/drama/pipelines", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: trimmedName,
          slug: trimmedSlug || null,
          enabled,
          auto_publish: true,
        }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.message || data.error || `HTTP ${res.status}`);
      }

      const created = await res.json();
      onClose();
      startTransition(() => {
        router.push(`/drama/${created.id}`);
        router.refresh();
      });
    } catch (err: any) {
      setErrorMsg(err.message || "Tạo pipeline thất bại.");
      setIsCreating(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-sm sm:p-6">
      <div className="w-full max-w-md rounded-3xl bg-white p-6 shadow-xl sm:p-8">
        <h3 className="text-xl font-extrabold text-slate-900">Tạo Drama Pipeline</h3>
        <p className="mt-1 text-sm text-slate-500">
          Tạo pipeline mới để bắt đầu nhập và quản lý nội dung phim.
        </p>

        {errorMsg && (
          <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm font-semibold text-rose-700">
            {errorMsg}
          </div>
        )}
        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <div>
            <label className={labelCls}>Tên pipeline *</label>
            <input
              required
              maxLength={200}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="VD: ReelShort Drama"
              className={inputCls}
            />
          </div>
          <div>
            <label className={labelCls}>Slug (optional)</label>
            <input
              value={slug}
              onChange={(e) => setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ""))}
              placeholder="VD: reelshort-drama"
              className={inputCls}
            />
            <p className="mt-1 text-xs text-slate-500">
              Nếu để trống, hệ thống sẽ tự tạo slug từ tên.
            </p>
          </div>
          <div className="flex items-center gap-6">
            <label className="flex items-center gap-2 text-sm font-semibold text-slate-700 cursor-pointer">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
                className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-600"
              />
              Enabled
            </label>
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
              {isCreating || isPending ? "Đang tạo..." : "Tạo pipeline"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export function DramaPipelineCard({
  pipeline,
  summary,
}: {
  pipeline: DramaPipelineDto;
  summary?: DramaSummaryDto;
}) {
  const total = summary?.inventory ?? 0;
  const seriesCount = summary?.series ?? 0;

  return (
    <Link
      href={`/drama/${pipeline.id}`}
      className="lift group flex flex-col rounded-2xl border border-slate-200/90 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.05)] transition hover:border-violet-300 hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500 to-purple-600 text-sm font-black text-white">
            D
          </span>
          <h3 className="min-w-0 truncate text-[15px] font-extrabold tracking-tight text-slate-900 group-hover:text-violet-700">
            {pipeline.name}
          </h3>
        </div>
        {pipeline.enabled ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-bold text-emerald-700 ring-1 ring-inset ring-emerald-200">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            ENABLED
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-bold text-slate-600 ring-1 ring-inset ring-slate-200">
            DISABLED
          </span>
        )}
      </div>

      <dl className="mt-4 grid grid-cols-3 gap-2 text-center">
        {[
          { l: "Sources", v: summary?.sources ?? "—" },
          { l: "Series", v: seriesCount ?? "—" },
          { l: "Episodes", v: total ?? "—" },
        ].map((s) => (
          <div key={s.l} className="rounded-xl bg-slate-50 px-2 py-2.5">
            <dt className="text-[10px] font-bold uppercase tracking-wider text-slate-400">{s.l}</dt>
            <dd className="tnum mt-0.5 text-lg font-extrabold text-slate-900">{s.v}</dd>
          </div>
        ))}
      </dl>

      <div className="mt-3">
        <div className="flex items-center justify-between text-[11px] font-semibold text-slate-500">
          <span>Episodes: {total}</span>
          <span className="tnum">Series: {seriesCount}</span>
        </div>
      </div>

      <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3 text-xs">
        <span className="flex items-center gap-1.5 text-slate-500">
          <span className="font-mono">/{pipeline.slug}</span>
        </span>
        <span className="flex items-center gap-0.5 font-bold text-violet-600 opacity-0 transition group-hover:opacity-100">
          Mở
          <IconChevronRight size={14} />
        </span>
      </div>
    </Link>
  );
}

// ---------- Import Discovery Modal ----------

function ImportDiscoveryModal({
  movie,
  pipelines,
  onClose,
  onSuccess,
}: {
  movie: DramaDiscoverySeriesDto;
  pipelines: DramaPipelineDto[];
  onClose: () => void;
  onSuccess: (pipelineId: string) => void;
}) {
  const [mode, setMode] = useState<"existing" | "new">(
    pipelines.length > 0 ? "existing" : "new"
  );
  const [selectedPipelineId, setSelectedPipelineId] = useState<string>(
    pipelines[0]?.id ?? ""
  );
  const [newPipelineName, setNewPipelineName] = useState<string>(
    movie.title ? `Drama: ${movie.title}` : "Drama Pipeline"
  );
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [statusStep, setStatusStep] = useState<string>("");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const handleImport = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isSubmitting) return;
    setIsSubmitting(true);
    setErrorMsg(null);

    try {
      let targetPipelineId = selectedPipelineId;

      if (mode === "new" || !targetPipelineId) {
        setStatusStep("Đang tạo pipeline mới...");
        const pRes = await fetch("/api/drama/pipelines", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: newPipelineName.trim() || movie.title || "Drama Pipeline",
            enabled: true,
            auto_publish: true,
          }),
        });
        if (!pRes.ok) {
          const d = await pRes.json().catch(() => ({}));
          throw new Error(d.error || d.message || "Không thể tạo pipeline.");
        }
        const createdPipeline = await pRes.json();
        targetPipelineId = createdPipeline.id;
      }

      setStatusStep("Đang gắn nguồn phim vào pipeline...");
      const srcRes = await fetch(
        `/api/drama/pipelines/${encodeURIComponent(targetPipelineId)}/sources`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            provider: movie.provider,
            external_series_id: movie.external_series_id,
            name: movie.title || `Series ${movie.external_series_id}`,
            enabled: true,
          }),
        }
      );
      if (!srcRes.ok) {
        const d = await srcRes.json().catch(() => ({}));
        throw new Error(d.error || d.message || "Không thể gắn nguồn phim vào pipeline.");
      }
      const createdSource = await srcRes.json();

      setStatusStep("Đang quét nội dung và tập phim từ nhà cung cấp...");
      const scanRes = await fetch(
        `/api/drama/sources/${encodeURIComponent(createdSource.id)}/scan`,
        {
          method: "POST",
        }
      );
      if (!scanRes.ok) {
        const d = await scanRes.json().catch(() => ({}));
        // Backend nests errors under `detail`: {detail: {error, message}}.
        const detail = (d as { detail?: { error?: unknown; message?: unknown } }).detail;
        const code =
          (typeof detail?.error === "string" && detail.error) ||
          (typeof d.error === "string" && d.error) ||
          null;
        const message =
          (typeof detail?.message === "string" && detail.message) ||
          (typeof d.message === "string" && d.message) ||
          "Quét nội dung tập phim thất bại.";
        throw new Error(code ? `${message} [${code}]` : message);
      }

      onSuccess(targetPipelineId);
    } catch (err: any) {
      setErrorMsg(err.message || "Lỗi khi nhập phim.");
      setIsSubmitting(false);
      setStatusStep("");
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm sm:p-6">
      <div className="w-full max-w-lg rounded-3xl bg-white p-6 shadow-2xl sm:p-8">
        <div className="flex items-start justify-between border-b border-slate-100 pb-4">
          <div className="flex items-center gap-3">
            <div className="relative h-14 w-11 shrink-0 overflow-hidden rounded-lg bg-slate-100">
              {movie.thumbnail_url ? (
                <img
                  src={movie.thumbnail_url}
                  alt={movie.title || "Poster"}
                  className="h-full w-full object-cover"
                />
              ) : (
                <div className="flex h-full w-full items-center justify-center text-slate-300">
                  <IconFilm size={20} />
                </div>
              )}
            </div>
            <div>
              <h3 className="line-clamp-1 text-base font-extrabold text-slate-900 sm:text-lg">
                Thêm Phim Vào Pipeline
              </h3>
              <p className="line-clamp-1 text-xs text-slate-500 font-medium">
                {movie.title || "Chưa có tên"} •{" "}
                <span className="font-bold text-indigo-600 uppercase">
                  {movie.provider}
                </span>
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={isSubmitting}
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

        <form onSubmit={handleImport} className="mt-5 space-y-4">
          {pipelines.length > 0 && (
            <div className="flex gap-4 border-b border-slate-100 pb-3">
              <label className="flex items-center gap-2 text-xs font-bold text-slate-700 cursor-pointer">
                <input
                  type="radio"
                  name="importMode"
                  checked={mode === "existing"}
                  onChange={() => setMode("existing")}
                  disabled={isSubmitting}
                  className="text-indigo-600 focus:ring-indigo-600"
                />
                Pipeline đã có
              </label>
              <label className="flex items-center gap-2 text-xs font-bold text-slate-700 cursor-pointer">
                <input
                  type="radio"
                  name="importMode"
                  checked={mode === "new"}
                  onChange={() => setMode("new")}
                  disabled={isSubmitting}
                  className="text-indigo-600 focus:ring-indigo-600"
                />
                Tạo Pipeline mới
              </label>
            </div>
          )}

          {mode === "existing" && pipelines.length > 0 ? (
            <div>
              <label className={labelCls}>Chọn Pipeline đích *</label>
              <select
                value={selectedPipelineId}
                onChange={(e) => setSelectedPipelineId(e.target.value)}
                disabled={isSubmitting}
                className={inputCls}
              >
                {pipelines.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} (/{p.slug})
                  </option>
                ))}
              </select>
            </div>
          ) : (
            <div>
              <label className={labelCls}>Tên Pipeline mới *</label>
              <input
                required
                type="text"
                value={newPipelineName}
                onChange={(e) => setNewPipelineName(e.target.value)}
                disabled={isSubmitting}
                placeholder="VD: Kho Phim Mới"
                className={inputCls}
              />
            </div>
          )}

          {statusStep && (
            <div className="flex items-center gap-2 rounded-xl bg-indigo-50 p-3 text-xs font-semibold text-indigo-700">
              <Spinner size={14} />
              <span>{statusStep}</span>
            </div>
          )}

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
              {isSubmitting ? <Spinner size={16} /> : "Nhập & Quét Ngay"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------- Live Discovery Component ----------

const DISCOVERY_PROVIDERS = [
  { id: "all", label: "Tất cả" },
  { id: "rapidix", label: "RapidIX" },
  { id: "netshort", label: "NetShort" },
  { id: "shortmax", label: "ShortMax" },
  { id: "starshort", label: "StarShort" },
  { id: "dramabox", label: "DramaBox" },
  { id: "flickshort", label: "FlickShort" },
];

const PROVIDER_LABELS: Record<string, string> = {
  shortmax: "ShortMax",
  netshort: "NetShort",
  starshort: "StarShort",
  dramabox: "DramaBox",
  flickshort: "FlickShort",
  rapidix: "RapidIX",
  reelshort_sdp: "ReelShort",
};

export function getProviderDisplayName(id: string): string {
  const norm = (id || "").toLowerCase();
  return PROVIDER_LABELS[norm] || (id ? id.charAt(0).toUpperCase() + id.slice(1) : "Không xác định");
}

export function getProviderWarningTitle(errs: DramaProviderErrorDto[]): string {
  if (!errs || errs.length === 0) return "";
  if (errs.length === 1) {
    const name = getProviderDisplayName(errs[0].provider);
    return `${name} tạm thời không khả dụng.`;
  }
  const names = errs.map((e) => getProviderDisplayName(e.provider)).join(", ");
  return `Một số nguồn phim đang tạm thời không khả dụng: ${names}.`;
}

export function DramaSearchClient({ pipelines }: { pipelines: DramaPipelineDto[] }) {
  const router = useRouter();
  const [selectedProvider, setSelectedProvider] = useState("all");
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<DramaDiscoverySeriesDto[]>([]);
  const [providerStatuses, setProviderStatuses] = useState<Record<string, DramaProviderStatusDto>>({});
  const [providerErrors, setProviderErrors] = useState<DramaProviderErrorDto[]>([]);
  const [showTechDetails, setShowTechDetails] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);
  const [importingMovie, setImportingMovie] = useState<DramaDiscoverySeriesDto | null>(null);

  const fetchDiscovery = async (prov: string, q: string) => {
    setLoading(true);
    setError(null);
    setHasSearched(true);
    try {
      const qParams = new URLSearchParams();
      qParams.set("provider", prov);
      if (q.trim()) qParams.set("query", q.trim());
      qParams.set("limit", "20");
      const res = await fetch(`/api/drama/discover?${qParams.toString()}`);
      if (!res.ok) {
        let msg = "Lỗi khi khám phá phim";
        try {
          const d = await res.json();
          if (d.error) msg = d.error;
          else if (d.message) msg = d.message;
        } catch {}
        throw new Error(msg);
      }
      const data: DramaDiscoveryResponseDto = await res.json();
      setItems(data.items || []);
      setProviderStatuses(data.providers || {});
      setProviderErrors(data.errors || []);
    } catch (err: any) {
      setError(err.message || "Lỗi khi kết nối hệ thống khám phá phim");
      setItems([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDiscovery(selectedProvider, query);
  }, [selectedProvider]);

  const onSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    fetchDiscovery(selectedProvider, query);
  };

  const onImportSuccess = (pipelineId: string) => {
    setImportingMovie(null);
    router.push(`/drama/${encodeURIComponent(pipelineId)}`);
  };

  return (
    <div className="mt-6 space-y-5">
      {/* Search Bar */}
      <div>
        <form onSubmit={onSearchSubmit} className="flex gap-2.5">
          <input
            type="text"
            className={inputCls}
            placeholder="Tìm phim theo từ khóa (RapidIX, StarShort, DramaBox)... hoặc để trống để xem bảng feed"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button type="submit" className={btnPrimary} disabled={loading}>
            {loading ? <Spinner /> : "Tìm kiếm"}
          </button>
        </form>
      </div>

      {/* Provider Filter Buttons */}
      <div className="-mx-1 flex items-center gap-1.5 overflow-x-auto px-1 pb-1">
        <span className="text-xs font-bold text-slate-400 mr-1 shrink-0 uppercase tracking-wider">
          Nguồn:
        </span>
        {DISCOVERY_PROVIDERS.map((p) => {
          const active = selectedProvider === p.id;
          return (
            <button
              key={p.id}
              type="button"
              onClick={() => setSelectedProvider(p.id)}
              className={`inline-flex shrink-0 items-center rounded-xl px-3 py-1.5 text-xs font-bold transition ${
                active
                  ? "bg-violet-600 text-white shadow-sm"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200"
              }`}
            >
              {p.label}
            </button>
          );
        })}
      </div>


      {/* Provider Warning / Notice Banner */}
      {providerErrors.length > 0 && (
        <div className="rounded-xl border border-amber-200/90 bg-amber-50/80 p-3.5 text-xs text-amber-800 shadow-sm transition">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <IconAlert size={16} className="text-amber-600 shrink-0" />
              <span className="font-semibold truncate">{getProviderWarningTitle(providerErrors)}</span>
            </div>
            <button
              type="button"
              onClick={() => setShowTechDetails((prev) => !prev)}
              className="text-[11px] font-medium text-amber-700 hover:text-amber-900 underline underline-offset-2 shrink-0 transition"
            >
              {showTechDetails ? "Ẩn chi tiết kỹ thuật ▴" : "Chi tiết kỹ thuật ▾"}
            </button>
          </div>
          {showTechDetails && (
            <div className="mt-2.5 pt-2 border-t border-amber-200/70 space-y-1 text-[11px] text-amber-900/80 font-mono">
              {providerErrors.map((e, idx) => (
                <div key={idx} className="flex items-center justify-between gap-2">
                  <span>
                    <strong className="font-semibold text-amber-950">{getProviderDisplayName(e.provider)}:</strong>{" "}
                    {e.status} {e.code ? `(${e.code})` : ""}
                  </span>
                  <span className="text-[10px] text-amber-700 truncate">{e.message}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-xs font-semibold text-rose-700">
          {error}
        </div>
      )}

      {/* Movie Grid */}
      {loading ? (
        <div className="flex flex-col items-center justify-center py-20 text-slate-400">
          <Spinner size={36} />
          <p className="mt-3 text-xs font-medium">Đang tải danh sách phim trực tiếp từ nhà cung cấp...</p>
        </div>
      ) : items.length > 0 ? (
        <div className="grid grid-cols-2 gap-3.5 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
          {items.map((series, idx) => (
            <div
              key={`${series.provider}-${series.external_series_id}-${idx}`}
              className="group flex flex-col overflow-hidden rounded-2xl border border-slate-200/90 bg-white shadow-sm transition hover:border-violet-300 hover:shadow-md"
            >
              <div className="relative aspect-[3/4] w-full overflow-hidden bg-slate-100">
                {series.thumbnail_url ? (
                  <img
                    src={series.thumbnail_url}
                    alt={series.title || "Poster"}
                    className="h-full w-full object-cover transition duration-300 group-hover:scale-105"
                  />
                ) : (
                  <div className="flex h-full w-full items-center justify-center text-slate-300">
                    <IconFilm size={28} />
                  </div>
                )}

                {/* Badges */}
                <div className="absolute left-2 top-2">
                  <span className="inline-flex items-center rounded-md bg-slate-900/80 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white backdrop-blur-sm">
                    {series.provider}
                  </span>
                </div>

                {series.total_episodes != null && (
                  <div className="absolute right-2 top-2">
                    <span className="inline-flex items-center rounded-md bg-emerald-600/85 px-2 py-0.5 text-[10px] font-bold text-white backdrop-blur-sm">
                      {series.total_episodes} Tập
                    </span>
                  </div>
                )}
              </div>

              <div className="flex flex-1 flex-col p-3">
                <h4 className="line-clamp-2 text-xs font-bold text-slate-900 group-hover:text-violet-700 sm:text-sm">
                  {series.title || "Chưa có tên"}
                </h4>
                {series.description && (
                  <p className="mt-1 line-clamp-2 text-[11px] text-slate-400">
                    {series.description}
                  </p>
                )}

                <div className="mt-auto pt-3">
                  <button
                    type="button"
                    onClick={() => setImportingMovie(series)}
                    className="w-full inline-flex min-h-[34px] items-center justify-center gap-1 rounded-xl bg-violet-50 px-2.5 py-1.5 text-xs font-bold text-violet-700 transition hover:bg-violet-600 hover:text-white"
                  >
                    <IconPlus size={13} />
                    Nhập vào Pipeline
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : hasSearched && !error ? (
        providerErrors.length > 0 ? (
          <div className="rounded-2xl border border-amber-200/90 bg-amber-50/80 p-8 text-center shadow-sm sm:p-12">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-amber-100 text-amber-600">
              <IconAlert size={28} />
            </div>
            <h3 className="mt-4 text-base font-extrabold text-amber-900">
              Hiện chưa thể tải danh sách phim từ nhà cung cấp. Vui lòng thử lại sau.
            </h3>
            <p className="mx-auto mt-1.5 max-w-md text-xs text-amber-700">
              Các nhà cung cấp thượng nguồn đang bảo trì hoặc gặp sự cố kết nối. Bạn có thể thử lại sau ít phút hoặc tìm kiếm với nhà cung cấp khác.
            </p>
            <div className="mt-4">
              <button
                type="button"
                onClick={() => setShowTechDetails((prev) => !prev)}
                className="text-xs font-semibold text-amber-800 hover:text-amber-950 underline underline-offset-2"
              >
                {showTechDetails ? "Ẩn chi tiết kỹ thuật ▴" : "Chi tiết kỹ thuật ▾"}
              </button>
              {showTechDetails && (
                <div className="mt-3 mx-auto max-w-md rounded-xl bg-amber-100/70 p-3 text-left font-mono text-[11px] text-amber-900 space-y-1">
                  {providerErrors.map((e, idx) => (
                    <div key={idx} className="flex items-center justify-between gap-2">
                      <strong>{getProviderDisplayName(e.provider)}:</strong>
                      <span>{e.status} {e.code ? `(${e.code})` : ""}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : (
          <EmptyState
            title="Không tìm thấy phim nào phù hợp."
            hint="Thử thay đổi bộ lọc nhà cung cấp hoặc tìm kiếm với từ khóa khác."
            icon={<IconFilm size={24} />}
          />
        )
      ) : null}

      {/* Import Modal */}
      {importingMovie && (
        <ImportDiscoveryModal
          movie={importingMovie}
          pipelines={pipelines}
          onClose={() => setImportingMovie(null)}
          onSuccess={onImportSuccess}
        />
      )}
    </div>
  );
}

export function DramaPipelineList({
  pipelines,
  summaries,
  error,
}: {
  pipelines: DramaPipelineDto[];
  summaries: Record<string, DramaSummaryDto>;
  error: string | null;
}) {
  const [query, setQuery] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [tab, setTab] = useState<"pipelines" | "search">("pipelines");
  const filtered = pipelines.filter((p) =>
    p.name.toLowerCase().includes(query.toLowerCase())
  );

  return (
    <>
      <PageHeader
        title="Drama"
        description="Quản lý nội dung Drama (ReelShort, ShortMax, DramaBox, v.v.)"
        actions={
          <button onClick={() => setCreateOpen(true)} className={btnPrimary}>
            <IconPlus size={15} className="mr-1" />
            Thêm pipeline
          </button>
        }
      />

      <div className="mt-6 border-b border-slate-200">
        <nav className="-mb-px flex gap-6">
          <button
            onClick={() => setTab("pipelines")}
            className={`whitespace-nowrap border-b-2 px-1 pb-3 text-sm font-medium transition ${
              tab === "pipelines"
                ? "border-violet-500 text-violet-600"
                : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-700"
            }`}
          >
            Quản lý Pipelines
          </button>
          <button
            onClick={() => setTab("search")}
            className={`whitespace-nowrap border-b-2 px-1 pb-3 text-sm font-medium transition ${
              tab === "search"
                ? "border-violet-500 text-violet-600"
                : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-700"
            }`}
          >
            Khám Phá Phim
          </button>
        </nav>
      </div>

      {tab === "pipelines" ? (
        <div className="mt-6">
          <div className="mb-4">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Tìm pipeline…"
              className="w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-900 shadow-sm outline-none placeholder:text-slate-400 focus:border-violet-300"
            />
          </div>
          {error ? (
            <div className="rounded-2xl border border-rose-200 bg-rose-50 p-8 text-center shadow-sm sm:p-12">
              <h3 className="mt-4 text-base font-extrabold text-rose-900">
                Không kết nối được backend Drama
              </h3>
              <p className="mx-auto mt-1.5 max-w-sm text-xs text-rose-700">{error}</p>
            </div>
          ) : filtered.length === 0 && pipelines.length === 0 ? (
            <div className="rounded-2xl border border-slate-200/90 bg-white p-8 text-center shadow-sm sm:p-12">
              <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-slate-100 text-slate-400">
                <IconFilm size={28} />
              </div>
              <h3 className="mt-4 text-base font-extrabold text-slate-900">
                Chưa có Drama pipeline nào.
              </h3>
              <p className="mx-auto mt-1.5 max-w-sm text-xs text-slate-500">
                Tạo pipeline Drama để bắt đầu quản lý series và episodes.
              </p>
              <div className="mt-5">
                <button onClick={() => setCreateOpen(true)} className={btnPrimary}>
                  <IconPlus size={15} className="mr-1" />
                  Tạo pipeline đầu tiên
                </button>
              </div>
            </div>
          ) : filtered.length === 0 ? (
            <div className="p-8 text-center text-sm text-slate-500">
              Không tìm thấy pipeline nào.
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {filtered.map((p) => (
                <DramaPipelineCard key={p.id} pipeline={p} summary={summaries[p.id]} />
              ))}
            </div>
          )}
        </div>
      ) : (
        <DramaSearchClient pipelines={pipelines} />
      )}

      {createOpen && <CreatePipelineModal onClose={() => setCreateOpen(false)} />}
    </>
  );
}