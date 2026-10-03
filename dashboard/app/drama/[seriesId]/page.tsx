"use client";

import { Shell } from "@/components/Shell";
import { useParams } from "next/navigation";
import Link from "next/link";
import { Badge, Card } from "@/components/ui";
import { IconBack, IconClock, IconPlay } from "@/components/icons";
import { getDramaSeries, getMockEpisodes } from "@/lib/drama-mock";

const toneStatus: Record<string, "green" | "indigo" | "amber" | "red"> = {
  ready: "green",
  published: "indigo",
  processing: "amber",
  error: "red",
};

const labelStatus: Record<string, string> = {
  ready: "Sẵn sàng",
  published: "Đã đăng",
  processing: "Đang xử lý",
  error: "Lỗi",
};

export default function DramaSeriesPage() {
  const params = useParams<{ seriesId: string }>();
  const series = getDramaSeries(params?.seriesId ?? "");
  const episodes = series ? getMockEpisodes(series.seriesId) : [];

  if (!series) {
    return (
      <Shell>
        <div className="w-full min-w-0">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <h1 className="truncate text-xl font-extrabold tracking-tight text-slate-900 sm:text-2xl">
                Drama
              </h1>
              <p className="mt-1 text-sm text-slate-500">Chi tiết bộ phim ngắn</p>
            </div>
            <Link
              href="/drama"
              className="inline-flex min-h-[44px] items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 shrink-0"
            >
              <IconBack size={15} />
              Thư viện
            </Link>
          </div>
          <Card className="mt-6 p-8 text-center">
            <p className="text-sm font-bold text-slate-900">Không tìm thấy bộ phim</p>
            <p className="mt-1.5 text-xs text-slate-500">Bộ phim này có thể đã bị xóa hoặc không tồn tại.</p>
            <Link
              href="/drama"
              className="mt-4 inline-flex min-h-[44px] items-center gap-1.5 rounded-xl bg-indigo-600 px-4 py-2 text-sm font-bold text-white"
            >
              ← Quay lại thư viện
            </Link>
          </Card>
        </div>
      </Shell>
    );
  }

  return (
    <Shell>
      <div className="w-full min-w-0">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <h1 className="text-xl font-extrabold tracking-tight text-slate-900 sm:text-2xl line-clamp-2">
              {series.title}
            </h1>
            <p className="mt-1 text-sm text-slate-500">
              {series.episodeCount} tập • {series.genre}
            </p>
          </div>
          <Link
            href="/drama"
            className="inline-flex min-h-[44px] items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 shrink-0"
          >
            <IconBack size={15} />
            Thư viện
          </Link>
        </div>

        <Card className="mt-6 overflow-hidden">
          <div className="flex flex-col gap-4 border-b border-slate-100 px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
            <div className="min-w-0">
              <h2 className="text-sm font-extrabold text-slate-900">Danh sách tập</h2>
              <p className="mt-0.5 text-xs text-slate-500">
                Hiển thị {episodes.length} trên {series.episodeCount} tập
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Badge tone="indigo">{series.genre}</Badge>
              <Badge tone="slate">{series.episodeCount} tập</Badge>
            </div>
          </div>
          <div className="divide-y divide-slate-100">
            {episodes.map((ep) => (
              <div
                key={ep.episodeId}
                className="flex flex-col gap-3 px-4 py-3.5 transition hover:bg-slate-50/80 sm:flex-row sm:items-center sm:justify-between sm:px-5"
              >
                <div className="flex items-center gap-3.5 min-w-0">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-slate-900 font-black text-xs text-white sm:text-sm">
                    #{ep.episodeNumber}
                  </span>
                  <div className="min-w-0">
                    <p className="truncate text-sm font-bold text-slate-900">{ep.title}</p>
                    <p className="mt-0.5 flex items-center gap-1.5 text-xs text-slate-500">
                      <IconClock size={13} />
                      {ep.duration}
                    </p>
                  </div>
                </div>
                <div className="flex items-center justify-between gap-3 sm:justify-end">
                  <Badge tone={toneStatus[ep.status]} dot>
                    {labelStatus[ep.status]}
                  </Badge>
                  <span className="inline-flex min-h-[44px] shrink-0 items-center justify-center rounded-xl bg-indigo-50 px-3.5 py-2 text-xs font-bold text-indigo-700 transition hover:bg-indigo-100">
                    <IconPlay size={14} />
                  </span>
                </div>
              </div>
            ))}
            {series.episodeCount > episodes.length && (
              <div className="px-5 py-4 text-center">
                <p className="text-xs font-semibold text-slate-500">
                  Đang hiển thị {episodes.length} tập đầu. API tích hợp sẽ hiển thị toàn bộ {series.episodeCount} tập.
                </p>
              </div>
            )}
          </div>
        </Card>
      </div>
    </Shell>
  );
}
