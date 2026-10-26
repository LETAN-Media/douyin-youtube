"use client";

import Link from "next/link";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { TikTokPipelineAutoToggle } from "@/components/tiktok/TikTokPipelineToggles";
import type { TikTokPipelineDto, TikTokSummaryDto } from "@/lib/tiktok-api";
import { btnPrimary, btnSecondary, inputCls, labelCls } from "@/components/ui";

function CreatePipelineModal({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [autoPublish, setAutoPublish] = useState(true);
  const [enabled, setEnabled] = useState(true);
  const [errorMsg, setErrorMsg] = useState("");
  const [isCreating, setIsCreating] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isCreating) return;

    const trimmedName = name.trim();
    const trimmedSlug = slug.replace(/-/g, " ").trim().replace(/\s+/g, "-").toLowerCase();

    if (!trimmedName || trimmedName.length > 200) {
      setErrorMsg("Tên không hợp lệ (max 200 ký tự).");
      return;
    }

    setErrorMsg("");
    setIsCreating(true);

    try {
      const res = await fetch("/api/tiktok/pipelines", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: trimmedName,
          slug: trimmedSlug || null,
          enabled,
          auto_publish: autoPublish,
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        setErrorMsg(errData.error || "Không thể tạo pipeline.");
        setIsCreating(false);
        return;
      }

      const created: TikTokPipelineDto = await res.json();
      router.refresh();
      router.push(`/tiktok/${created.id}`);
    } catch (_err) {
      setErrorMsg("Không thể kết nối.");
      setIsCreating(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
      <div className="w-full max-w-md rounded-3xl border border-slate-200 bg-white p-6 shadow-2xl">
        <h3 className="text-lg font-extrabold tracking-tight text-slate-900">
          Thêm TikTok pipeline
        </h3>
        {errorMsg && (
          <div className="mt-3 rounded-lg bg-rose-50 p-3 text-sm text-rose-600 border border-rose-200">
            {errorMsg}
          </div>
        )}
        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <div>
            <label className={labelCls}>Tên pipeline</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className={inputCls}
              placeholder="VD: Nội dung giải trí"
              maxLength={200}
              required
              disabled={isCreating}
            />
          </div>
          <div>
            <label className={labelCls}>Slug (định danh URL)</label>
            <input
              type="text"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              className={inputCls}
              placeholder="tự động sinh nếu để trống"
              disabled={isCreating}
            />
          </div>
          <div>
            <label className="flex items-center gap-2 text-sm font-medium text-slate-700">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
                disabled={isCreating}
              />
              Pipeline bật
            </label>
          </div>
          <div>
            <label className="flex items-center gap-2 text-sm font-medium text-slate-700">
              <input
                type="checkbox"
                checked={autoPublish}
                onChange={(e) => setAutoPublish(e.target.checked)}
                disabled={isCreating}
              />
              AUTO ON (đăng tự động)
            </label>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className={btnSecondary}
              disabled={isCreating}
            >
              Hủy
            </button>
            <button type="submit" className={btnPrimary} disabled={isCreating}>
              {isCreating ? "Đang tạo…" : "Tạo pipeline"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export function TikTokPipelineList({
  pipelines,
  summaries,
  summaryErrors = {},
  error,
}: {
  pipelines: TikTokPipelineDto[];
  summaries: Record<string, TikTokSummaryDto>;
  summaryErrors?: Record<string, string>;
  error: string | null;
}) {
  const [showCreate, setShowCreate] = useState(false);
  const router = useRouter();

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-extrabold text-slate-900">TikTok Pipelines</h1>
          <p className="text-sm text-slate-500">
            Quản lý pipeline TikTok → YouTube với AUTO ON/OFF riêng lẻ.
          </p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className={btnPrimary}
        >
          Thêm pipeline
        </button>
      </div>

      <div className="mb-6 flex gap-2">
        <span className="inline-flex min-h-[44px] items-center rounded-xl bg-indigo-600 px-4 py-2 text-xs font-bold text-white shadow-sm">
          Auto Pipelines
        </span>
        <Link
          href="/tiktok/manual"
          className="inline-flex min-h-[44px] items-center rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-bold text-slate-700 shadow-sm transition hover:bg-slate-50"
        >
          Manual Publish
        </Link>
      </div>

      {error && (
        <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between rounded-2xl border border-rose-200 bg-rose-50/90 p-4 shadow-sm text-sm text-rose-800">
          <div className="flex items-start gap-2.5">
            <span className="text-rose-600 mt-0.5 text-base font-bold">⚠️</span>
            <div>
              <p className="font-bold text-rose-900">Không thể tải danh sách TikTok Pipelines</p>
              <p className="mt-0.5 text-xs text-rose-700 leading-relaxed">{error}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => router.refresh()}
            className="inline-flex min-h-[38px] items-center justify-center gap-1.5 rounded-xl bg-rose-600 px-4 py-2 text-xs font-bold text-white shadow-sm transition hover:bg-rose-700 shrink-0 self-start sm:self-auto"
          >
            Thử lại
          </button>
        </div>
      )}

      {showCreate && <CreatePipelineModal onClose={() => setShowCreate(false)} />}

      {!showCreate && pipelines.length === 0 && !error && (
        <div className="py-12 text-center text-slate-500">
          Chưa có pipeline nào. Tạo pipeline đầu tiên để bắt đầu.
        </div>
      )}

      <div className="grid gap-4">
        {pipelines.map((p) => (
          <PipelineCard
            key={p.id}
            pipeline={p}
            initialSummary={summaries[p.id]}
            initialError={summaryErrors[p.id]}
            onSelect={() => router.push(`/tiktok/${p.id}`)}
          />
        ))}
      </div>
    </div>
  );
}

function PipelineCard({
  pipeline,
  initialSummary,
  initialError,
  onSelect,
}: {
  pipeline: TikTokPipelineDto;
  initialSummary?: TikTokSummaryDto;
  initialError?: string;
  onSelect: () => void;
}) {
  const [summary, setSummary] = useState<TikTokSummaryDto | undefined>(initialSummary);
  const [error, setError] = useState<string | null>(initialError || null);
  const [retrying, setRetrying] = useState(false);

  useEffect(() => {
    if (initialSummary) {
      setSummary(initialSummary);
      setError(null);
    } else if (initialError) {
      setError(initialError);
    }
  }, [initialSummary, initialError]);

  const handleRetry = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setRetrying(true);
    setError(null);
    try {
      const res = await fetch(`/api/tiktok/flow/${encodeURIComponent(pipeline.id)}`, { cache: "no-store" });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.error || `HTTP ${res.status}`);
      }
      const raw = await res.json();
      const s = raw.summary || {};
      const sourcesCount = raw.sources !== undefined && typeof raw.sources === "number"
        ? raw.sources
        : (raw.sources_count ?? s.total_sources ?? 0);
      const destinationsCount = raw.destinations !== undefined && typeof raw.destinations === "number"
        ? raw.destinations
        : (s.total_destinations ?? 0);
      const inventory = raw.inventory ?? raw.inventory_count ?? s.inventory ?? s.unpublished ?? 0;
      const published = raw.published ?? raw.published_count ?? s.published ?? 0;
      const queued = raw.queued ?? raw.queued_count ?? s.queued ?? s.queue_count ?? 0;
      const failed = raw.failed ?? raw.failed_count ?? s.failed ?? 0;
      const processing = raw.processing ?? raw.processing_count ?? s.processing ?? 0;

      const sum: TikTokSummaryDto = {
        pipeline_id: pipeline.id,
        pipeline,
        sources: Number(sourcesCount) || 0,
        inventory: Number(inventory) || 0,
        destinations: Number(destinationsCount) || 0,
        published: Number(published) || 0,
        failed: Number(failed) || 0,
        queued: Number(queued) || 0,
        processing: Number(processing) || 0,
        auto_publish: Boolean(pipeline.auto_publish),
      };
      setSummary(sum);
      setError(null);
    } catch (err: any) {
      setError(err instanceof Error ? err.message : "Không thể tải lại thống kê.");
    } finally {
      setRetrying(false);
    }
  };

  return (
    <div
      className="group relative overflow-hidden rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition hover:shadow-md cursor-pointer"
      onClick={onSelect}
    >
      <div className="absolute top-3 right-3" onClick={(e) => e.stopPropagation()}>
        <TikTokPipelineAutoToggle
          pipelineId={pipeline.id}
          initialAutoPublish={pipeline.auto_publish}
          enabled={pipeline.enabled}
        />
      </div>

      <div>
        <h3 className="text-xl font-bold text-slate-900">{pipeline.name}</h3>
        <p className="text-sm text-slate-500">@{pipeline.slug}</p>
      </div>

      {summary && (
        <div className="mt-4 grid grid-cols-4 gap-2 text-center">
          <div className="rounded-xl bg-slate-50/80 p-2.5 border border-slate-100">
            <span className="text-2xl font-bold text-slate-900">
              {typeof summary.inventory === "number" ? summary.inventory : "—"}
            </span>
            <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Inventory</p>
          </div>
          <div className="rounded-xl bg-indigo-50/50 p-2.5 border border-indigo-100/60">
            <span className="text-2xl font-bold text-indigo-600">
              {typeof summary.published === "number" ? summary.published : "—"}
            </span>
            <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Published</p>
          </div>
          <div className="rounded-xl bg-amber-50/50 p-2.5 border border-amber-100/60">
            <span className="text-2xl font-bold text-amber-600">
              {typeof summary.queued === "number" ? summary.queued : "—"}
            </span>
            <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Queued</p>
          </div>
          <div className="rounded-xl bg-rose-50/50 p-2.5 border border-rose-100/60">
            <span className={`text-2xl font-bold ${summary.failed > 0 ? "text-rose-600" : "text-slate-400"}`}>
              {typeof summary.failed === "number" ? summary.failed : "—"}
            </span>
            <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Failed</p>
          </div>
        </div>
      )}

      {error && !summary && (
        <div
          className="mt-4 flex items-center justify-between rounded-xl border border-rose-200 bg-rose-50/90 px-3.5 py-2.5 text-xs text-rose-700 shadow-sm"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="flex items-center gap-2 truncate">
            <span>⚠️</span>
            <span className="truncate">{error}</span>
          </div>
          <button
            type="button"
            onClick={handleRetry}
            disabled={retrying}
            className="ml-2 inline-flex shrink-0 items-center rounded-lg bg-rose-600 px-2.5 py-1 text-[11px] font-bold text-white shadow-sm hover:bg-rose-700 disabled:opacity-50 transition"
          >
            {retrying ? "Đang tải…" : "Thử lại"}
          </button>
        </div>
      )}

      {!summary && !error && (
        <div className="mt-4 grid grid-cols-4 gap-2 text-center animate-pulse">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="rounded-xl bg-slate-100 p-2.5 h-16 flex flex-col items-center justify-center">
              <div className="h-6 w-10 bg-slate-200 rounded mb-1" />
              <div className="h-3 w-12 bg-slate-200 rounded" />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
