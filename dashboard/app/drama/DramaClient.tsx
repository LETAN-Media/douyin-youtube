"use client";

import Link from "next/link";
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { PageHeader, btnPrimary, btnSecondary, inputCls, labelCls } from "@/components/ui";
import { IconChevronRight, IconFilm, IconPlus } from "@/components/icons";
import type { DramaPipelineDto, DramaSummaryDto } from "@/lib/drama-api";

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

    setErrorMsg("");
    setIsCreating(true);

    try {
      const res = await fetch("/api/drama/pipelines", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: trimmedName,
          slug: trimmedSlug || null,
          enabled,
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        if (errData.error === "PIPELINE_ALREADY_EXISTS" || (errData.error || "").includes("UNIQUE constraint failed")) {
          setErrorMsg("Slug pipeline đã tồn tại.");
        } else {
          setErrorMsg(errData.error || "Không thể tạo pipeline.");
        }
        setIsCreating(false);
        return;
      }

      const created = await res.json();
      startTransition(() => {
        router.refresh();
        router.push(`/drama/${created.id}`);
      });
    } catch (err: any) {
      setErrorMsg("Không thể kết nối.");
      setIsCreating(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/50 p-4 backdrop-blur-[2px] sm:items-center">
      <div className="fade-up w-full max-w-md rounded-3xl border border-slate-200 bg-white p-6 shadow-2xl">
        <h3 className="text-lg font-extrabold tracking-tight text-slate-900">
          Thêm drama pipeline mới
        </h3>
        {errorMsg && (
          <div className="mt-3 rounded-lg bg-rose-50 p-3 text-sm text-rose-600 border border-rose-200">
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
  const filtered = pipelines.filter((p) =>
    p.name.toLowerCase().includes(query.toLowerCase()),
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
      <div className="mt-4">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Tìm pipeline…"
          className="w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-900 shadow-sm outline-none placeholder:text-slate-400 focus:border-violet-300"
        />
      </div>

      <div className="mt-6">
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

      {createOpen && <CreatePipelineModal onClose={() => setCreateOpen(false)} />}
    </>
  );
}