"use client";

import Link from "next/link";
import { useState } from "react";
import { PageHeader } from "@/components/ui";
import { IconChevronRight, IconPlay } from "@/components/icons";
import type { FacebookPipelineDto, FacebookSummaryDto } from "@/lib/facebook-api";

export function FacebookPipelineCard({
  pipeline,
  summary,
}: {
  pipeline: FacebookPipelineDto;
  summary?: FacebookSummaryDto;
}) {
  const total = summary?.inventory ?? 0;
  const published = summary?.published ?? 0;
  const done = total > 0 ? Math.round((published / total) * 100) : 0;
  const failed = summary?.failed ?? 0;

  return (
    <Link
      href={`/facebook/${pipeline.id}`}
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
          { l: "Sources", v: summary?.sources ?? "—" },
          { l: "Inventory", v: summary?.inventory ?? "—" },
          { l: "Dest.", v: summary?.destinations ?? "—" },
        ].map((s) => (
          <div key={s.l} className="rounded-xl bg-slate-50 px-2 py-2.5">
            <dt className="text-[10px] font-bold uppercase tracking-wider text-slate-400">{s.l}</dt>
            <dd className="tnum mt-0.5 text-lg font-extrabold text-slate-900">{s.v}</dd>
          </div>
        ))}
      </dl>

      <div className="mt-3">
        <div className="flex items-center justify-between text-[11px] font-semibold text-slate-500">
          <span>Published {published}/{total}</span>
          <span className="tnum">{done}%</span>
        </div>
        <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
          <div
            className="h-full rounded-full bg-indigo-500 transition-all"
            style={{ width: `${done}%` }}
          />
        </div>
      </div>

      <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3 text-xs">
        <span className="flex items-center gap-1.5 text-slate-500">
          <span className="font-mono">/{pipeline.slug}</span>
        </span>
        {failed > 0 ? (
          <span className="flex items-center gap-1 font-bold text-rose-600">
            {failed} failed
          </span>
        ) : (
          <span className="flex items-center gap-1 font-bold text-emerald-600">
            {summary ? "Đồng bộ" : "Chưa có stats"}
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

export function FacebookPipelineList({
  pipelines,
  summaries,
  error,
}: {
  pipelines: FacebookPipelineDto[];
  summaries: Record<string, FacebookSummaryDto>;
  error: string | null;
}) {
  const [query, setQuery] = useState("");
  const filtered = pipelines.filter((p) =>
    p.name.toLowerCase().includes(query.toLowerCase()),
  );

  return (
    <>
      <PageHeader
        title="Facebook"
        description="Quản lý và đăng nội dung Facebook"
      />
      <div className="mt-4">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Tìm pipeline…"
          className="w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-900 shadow-sm outline-none placeholder:text-slate-400 focus:border-indigo-300"
        />
      </div>

      <div className="mt-6">
        {error ? (
          <div className="rounded-2xl border border-rose-200 bg-rose-50 p-8 text-center shadow-sm sm:p-12">
            <h3 className="mt-4 text-base font-extrabold text-rose-900">
              Không kết nối được backend Facebook
            </h3>
            <p className="mx-auto mt-1.5 max-w-sm text-xs text-rose-700">{error}</p>
          </div>
        ) : filtered.length === 0 ? (
          <div className="rounded-2xl border border-slate-200/90 bg-white p-8 text-center shadow-sm sm:p-12">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-slate-100 text-slate-400">
              <IconPlay size={28} />
            </div>
            <h3 className="mt-4 text-base font-extrabold text-slate-900">
              Chưa có Facebook pipeline nào.
            </h3>
            <p className="mx-auto mt-1.5 max-w-sm text-xs text-slate-500">
              Tạo pipeline Facebook để bắt đầu quản lý và đăng nội dung lên Facebook.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {filtered.map((p) => (
              <FacebookPipelineCard key={p.id} pipeline={p} summary={summaries[p.id]} />
            ))}
          </div>
        )}
      </div>
    </>
  );
}
