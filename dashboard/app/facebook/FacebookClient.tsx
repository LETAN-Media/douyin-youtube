"use client";

import Link from "next/link";
import { PageHeader } from "@/components/ui";
import { IconChevronRight, IconPlay } from "@/components/icons";
import { FACEBOOK_PIPELINES, getFacebookPipeline } from "@/lib/facebook-mock";
import { useRouter } from "next/navigation";
import { useState } from "react";

export function FacebookPipelineCard({ pipeline }: { pipeline: ReturnType<typeof getFacebookPipeline> }) {
  if (!pipeline) return null;
  const done = pipeline.total > 0 ? Math.round((pipeline.publishedTotal / pipeline.total) * 100) : 0;
  const noInventory = pipeline.inventory <= 0;
  const reasonLabel = !pipeline.enabled
    ? null
    : pipeline.autoReason === "NO_AVAILABLE_INVENTORY" || (noInventory && pipeline.publishedToday === 0)
      ? "Auto ON · No videos available"
      : pipeline.autoReason === "WAITING_NEXT_SLOT"
        ? "Auto ON · Waiting next slot"
        : pipeline.autoReason === "DAILY_LIMIT_REACHED"
          ? "Auto ON · Daily limit reached"
          : pipeline.autoReason === "SCHEDULER_DISABLED"
            ? "Auto ON · Scheduler disabled"
            : pipeline.autoReason === "WORKER_ERROR"
              ? "Auto ON · Worker error"
              : null;

  return (
    <Link
      href={`/facebook/${pipeline.pipelineId}`}
      className="lift group flex flex-col rounded-2xl border border-slate-200/90 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.05)] transition hover:border-indigo-300 hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-sky-500 to-blue-600 text-sm font-black text-white">
            F
          </span>
          <h3 className="min-w-0 truncate text-[15px] font-extrabold tracking-tight text-slate-900 group-hover:text-indigo-700">
            {pipeline.name}
          </h3>
        </div>
        {pipeline.enabled ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-bold text-emerald-700 ring-1 ring-inset ring-emerald-200">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            AUTO ON
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-bold text-slate-600 ring-1 ring-inset ring-slate-200">
            AUTO OFF
          </span>
        )}
      </div>

      <dl className="mt-4 grid grid-cols-3 gap-2 text-center">
        {[
          { l: "Sources", v: pipeline.sources },
          { l: "Inventory", v: pipeline.inventory },
          { l: "Dest.", v: pipeline.destinations },
        ].map((s) => (
          <div key={s.l} className="rounded-xl bg-slate-50 px-2 py-2.5">
            <dt className="text-[10px] font-bold uppercase tracking-wider text-slate-400">{s.l}</dt>
            <dd className="tnum mt-0.5 text-lg font-extrabold text-slate-900">{s.v}</dd>
          </div>
        ))}
      </dl>

      <div className="mt-3">
        <div className="flex items-center justify-between text-[11px] font-semibold text-slate-500">
          <span>Published {pipeline.publishedTotal}/{pipeline.total}</span>
          <span className="tnum">{done}%</span>
        </div>
        <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
          <div
            className="h-full rounded-full bg-indigo-500 transition-all"
            style={{ width: `${done}%` }}
          />
        </div>
        {reasonLabel ? (
          <p className="mt-2 rounded-lg bg-amber-50 px-2.5 py-1.5 text-[11px] font-bold text-amber-700">
            {reasonLabel}
          </p>
        ) : null}
      </div>

      <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3 text-xs">
        <span className="flex items-center gap-1.5 text-slate-500">
          <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
          </svg>
          {pipeline.nextUpload ? `21:00 03-10` : "—"}
        </span>
        {pipeline.failed > 0 ? (
          <span className="flex items-center gap-1 font-bold text-rose-600">
            {pipeline.failed} failed
          </span>
        ) : (
          <span className="flex items-center gap-1 font-bold text-emerald-600">
            Hôm nay +{pipeline.publishedToday}
          </span>
        )}
        <span className="flex items-center gap-0.5 font-bold text-indigo-600 opacity-0 transition group-hover:opacity-100">
          Mở
          <IconChevronRight size={14} />
        </span>
      </div>
    </Link>
  );
}

export default function FacebookPage() {
  const router = useRouter();
  const [query, setQuery] = useState("");

  const filtered = FACEBOOK_PIPELINES.filter((p) =>
    p.name.toLowerCase().includes(query.toLowerCase()),
  );

  return (
    <>
      <PageHeader
        title="Facebook"
        description="Quản lý và đăng nội dung Facebook"
      />

      <div className="mt-6">
        {filtered.length === 0 ? (
          <div className="rounded-2xl border border-slate-200/90 bg-white p-8 text-center shadow-sm sm:p-12">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-slate-100 text-slate-400">
              <IconPlay size={28} />
            </div>
            <h3 className="mt-4 text-base font-extrabold text-slate-900">
              Chưa có Facebook pipeline nào.
            </h3>
            <p className="mt-1.5 text-xs text-slate-500 max-w-sm mx-auto">
              Tạo pipeline Facebook để bắt đầu quản lý và đăng nội dung lên Facebook.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {filtered.map((p) => (
              <FacebookPipelineCard key={p.pipelineId} pipeline={getFacebookPipeline(p.pipelineId)} />
            ))}
          </div>
        )}
      </div>
    </>
  );
}
