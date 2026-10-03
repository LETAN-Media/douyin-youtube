"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import Link from "next/link";
import { Badge, Card, PageHeader } from "@/components/ui";
import { IconPlay, IconRefresh, IconSearch } from "@/components/icons";
import type { DramaSeries } from "@/lib/drama-mock";

interface DramaLibraryClientProps {
  series: DramaSeries[];
}

export function DramaLibraryClient({ series }: DramaLibraryClientProps) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);

  const filtered = series.filter((s) =>
    `${s.title} ${s.genre}`.toLowerCase().includes(query.toLowerCase()),
  );

  const handleRefresh = async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/drama/library", { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data)) {
          router.refresh();
        }
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <PageHeader
        title="Drama Library"
        description="Danh sách bộ phim ngắn đã quét"
        actions={
          <div className="flex items-center gap-2">
            <div className="relative">
              <IconSearch size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Tìm phim, thể loại..."
                className="w-full rounded-xl border border-slate-200 bg-white pl-9 pr-3 py-2 text-sm font-semibold text-slate-900 shadow-sm outline-none transition placeholder:text-slate-400 hover:border-slate-300 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100 sm:w-64"
              />
            </div>
            <button
              type="button"
              onClick={handleRefresh}
              disabled={loading}
              className="inline-flex min-h-[44px] items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50"
            >
              <IconRefresh size={14} />
              {loading ? "Đang tải…" : "Làm mới"}
            </button>
          </div>
        }
      />

      <div className="mt-6">
        {filtered.length === 0 ? (
          <Card className="p-8 sm:p-12 text-center">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-indigo-50 text-indigo-600">
              <IconPlay size={28} />
            </div>
            <h3 className="mt-4 text-base font-extrabold text-slate-900">
              Chưa có phim ngắn nào trong thư viện.
            </h3>
            <p className="mt-1.5 text-xs text-slate-500 max-w-sm mx-auto">
              Khi hệ thống quét được nguồn Douyin, danh sách drama sẽ hiển thị tại đây.
            </p>
          </Card>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {filtered.map((s) => (
              <Link
                key={s.seriesId}
                href={`/drama/${s.seriesId}`}
                className="group flex flex-col justify-between rounded-2xl border border-slate-200/90 bg-white p-5 shadow-sm transition hover:border-indigo-300 hover:shadow-md"
              >
                <div className="min-w-0">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h3 className="truncate text-base font-extrabold text-slate-900 group-hover:text-indigo-600 transition">
                        {s.title}
                      </h3>
                      <p className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
                        <span className="font-semibold">{s.episodeCount} tập</span>
                        <span aria-hidden className="text-slate-300">·</span>
                        <span>{s.genre}</span>
                      </p>
                    </div>
                    <Badge tone="indigo">{s.genre}</Badge>
                  </div>
                </div>
                <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3.5">
                  <span className="text-[11px] font-bold uppercase tracking-[0.08em] text-slate-500">
                    Xem danh sách tập →
                  </span>
                  <span className="inline-flex h-8 w-8 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600">
                    <IconPlay size={16} />
                  </span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
