"use client";

import Link from "next/link";
import { useState } from "react";
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
  error,
}: {
  pipelines: TikTokPipelineDto[];
  summaries: Record<string, TikTokSummaryDto>;
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
        <div className="mb-4 rounded-lg bg-rose-50 p-3 text-sm text-rose-600 border border-rose-200">
          {error}
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
            summary={summaries[p.id]}
            onSelect={() => router.push(`/tiktok/${p.id}`)}
          />
        ))}
      </div>
    </div>
  );
}

function PipelineCard({
  pipeline,
  summary,
  onSelect,
}: {
  pipeline: TikTokPipelineDto;
  summary?: TikTokSummaryDto;
  onSelect: () => void;
}) {
  const hasSummary = !!summary;
  const inventoryCount = summary?.inventory ?? 0;
  const publishedCount = summary?.published ?? 0;
  const queuedCount = summary?.queued ?? 0;
  const failedCount = summary?.failed ?? 0;

  return (
    <div
      className="group relative overflow-hidden rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition hover:shadow-md"
      onClick={onSelect}
    >
      <div className="absolute top-3 right-3">
        <TikTokPipelineAutoToggle
          pipelineId={pipeline.id}
          initialAutoPublish={pipeline.auto_publish}
          enabled={pipeline.enabled}
        />
      </div>

      <div className="cursor-pointer">
        <h3 className="text-xl font-bold text-slate-900">{pipeline.name}</h3>
        <p className="text-sm text-slate-500">@{pipeline.slug}</p>
      </div>

      {hasSummary && (
        <div className="mt-4 grid grid-cols-4 gap-2 text-center">
          <div>
            <span className="text-2xl font-bold text-slate-900">{inventoryCount}</span>
            <p className="text-xs text-slate-500">Inventory</p>
          </div>
          <div>
            <span className="text-2xl font-bold text-indigo-600">{publishedCount}</span>
            <p className="text-xs text-slate-500">Published</p>
          </div>
          <div>
            <span className="text-2xl font-bold text-amber-600">{queuedCount}</span>
            <p className="text-xs text-slate-500">Queued</p>
          </div>
          <div>
            <span className="text-2xl font-bold text-rose-600">{failedCount}</span>
            <p className="text-xs text-slate-500">Failed</p>
          </div>
        </div>
      )}

      {!hasSummary && (
        <div className="mt-3 text-xs text-slate-400">Đang tải…</div>
      )}
    </div>
  );
}
