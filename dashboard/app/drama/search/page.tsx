"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import {
  Card,
  CardHeader,
  PageHeader,
  Spinner,
  inputCls,
  btnPrimary,
  Badge,
} from "@/components/ui";
import { DramaSeriesDto } from "@/lib/drama-api";

export default function DramaSearchPage() {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<DramaSeriesDto[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);

  const performSearch = async (q: string) => {
    setLoading(true);
    setError(null);
    setHasSearched(true);
    try {
      const qParams = new URLSearchParams();
      if (q) qParams.set("query", q);
      qParams.set("limit", "100");
      const res = await fetch(`/api/drama/series?${qParams.toString()}`);
      if (!res.ok) {
        let msg = "Lỗi khi tìm kiếm phim";
        try {
           const d = await res.json();
           if (d.error) msg = d.error;
        } catch {}
        throw new Error(msg);
      }
      const data = await res.json();
      setItems(data.items || []);
    } catch (err: any) {
      setError(err.message || "Lỗi khi tìm kiếm phim");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    // Initial fetch to show hot/recent items if no query
    performSearch("");
  }, []);

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    performSearch(query);
  };

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6 lg:px-8">
      <div className="mb-6">
        <PageHeader
          eyebrow="Drama"
          title="Tìm Kiếm Phim"
          description="Tìm kiếm phim có sẵn trong hệ thống"
        />
      </div>

      <div className="mb-8">
        <form onSubmit={onSubmit} className="flex gap-3">
          <input
            type="text"
            className={inputCls}
            placeholder="Nhập tên phim cần tìm..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button type="submit" className={btnPrimary} disabled={loading}>
            {loading ? <Spinner /> : "Tìm kiếm"}
          </button>
        </form>
      </div>

      {error && (
        <div className="mb-8 rounded-xl bg-rose-50 p-4 text-sm font-medium text-rose-600">
          {error}
        </div>
      )}

      {loading && items.length === 0 ? (
        <div className="flex justify-center p-12">
          <Spinner size={32} />
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
          {items.map((series) => {
            const href = series.pipeline_id ? `/drama/${encodeURIComponent(series.pipeline_id)}` : "#";
            return (
            <Link
              key={series.id}
              href={href}
              className="group flex flex-col overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-slate-200 transition hover:shadow-md hover:ring-indigo-500"
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
                    No Image
                  </div>
                )}
                {series.total_episodes != null && (
                  <div className="absolute right-2 top-2">
                    <Badge tone="green">{series.total_episodes} Tập</Badge>
                  </div>
                )}
                <div className="absolute left-2 top-2">
                  <Badge tone="amber">Hot</Badge>
                </div>
              </div>
              <div className="flex flex-1 flex-col p-3">
                <h3 className="line-clamp-2 text-sm font-bold text-slate-900 group-hover:text-indigo-600">
                  {series.title || "Unknown Title"}
                </h3>
                {series.description && (
                  <p className="mt-1 line-clamp-2 text-xs text-slate-500">
                    {series.description}
                  </p>
                )}
              </div>
            </Link>
            );
          })}
        </div>
      )}

      {!loading && hasSearched && items.length === 0 && !error && (
        <div className="rounded-xl border border-dashed border-slate-300 py-16 text-center">
          <p className="text-slate-500">Không tìm thấy phim nào phù hợp.</p>
        </div>
      )}
    </div>
  );
}
