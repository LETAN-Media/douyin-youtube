"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { actionGetOauthUrl } from "@/lib/actions";

interface DailyRow {
  date: string;
  views: number;
  watch_minutes: number;
  avg_view_duration: number;
  avg_view_percentage: number;
  likes: number;
  comments: number;
  shares: number;
  subs_gained: number;
  subs_lost: number;
}

interface TopVideo {
  video_id: string;
  title?: string | null;
  thumbnail?: string | null;
  views: number;
  watch_minutes: number;
  avg_view_duration: number;
  likes: number;
  comments: number;
  subs_gained: number;
}

interface AnalyticsData {
  summary: Record<string, number>;
  daily: DailyRow[];
  top_videos: TopVideo[];
  traffic_sources: { source: string; views: number; watch_minutes: number }[];
  search_terms: { term: string; views: number }[];
  oauth_ready: boolean;
  oauth_reason?: string | null;
  reconnect_required: boolean;
  start: string;
  end: string;
}

const RANGES = ["7d", "28d", "90d", "1y"] as const;

function LineChart({ points, color }: { points: number[]; color: string }) {
  const w = 320;
  const h = 90;
  const max = Math.max(1, ...points);
  const step = points.length > 1 ? w / (points.length - 1) : w;
  const d = points
    .map((v, i) => `${i === 0 ? "M" : "L"}${(i * step).toFixed(1)},${(h - 6 - (v / max) * (h - 14)).toFixed(1)}`)
    .join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full" role="img">
      <path d={d} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" />
    </svg>
  );
}

function BarList({ rows, maxRows = 8 }: { rows: { label: string; value: number }[]; maxRows?: number }) {
  const top = rows.slice(0, maxRows);
  const max = Math.max(1, ...top.map((r) => r.value));
  return (
    <div className="space-y-1.5">
      {top.map((r) => (
        <div key={r.label} className="min-w-0">
          <div className="flex items-baseline justify-between gap-2 text-[11px]">
            <span className="truncate font-semibold text-slate-700">{r.label}</span>
            <span className="shrink-0 font-mono text-slate-500">{r.value.toLocaleString()}</span>
          </div>
          <div className="mt-0.5 h-1.5 overflow-hidden rounded-full bg-slate-100">
            <div
              className="h-full rounded-full bg-indigo-500"
              style={{ width: `${Math.max(2, Math.round((r.value / max) * 100))}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

export function ChannelAnalytics({ destinationId }: { destinationId: string }) {
  const [range, setRange] = useState<string>("28d");
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(
    async (r: string) => {
      setLoading(true);
      try {
        const res = await fetch(`/api/channels/${destinationId}/analytics?range=${r}`);
        if (res.ok) setData(await res.json());
      } catch {
        /* noop */
      } finally {
        setLoading(false);
      }
    },
    [destinationId],
  );

  useEffect(() => {
    load(range);
  }, [load, range]);

  const refresh = async () => {
    setRefreshing(true);
    setNotice(null);
    try {
      const res = await fetch(`/api/channels/${destinationId}/analytics/refresh`, { method: "POST" });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || "Refresh thất bại");
      setNotice("Đang refresh analytics nền — dữ liệu mới sẽ hiện sau vài phút.");
      setTimeout(() => load(range), 15000);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Refresh thất bại");
    } finally {
      setRefreshing(false);
    }
  };

  const reconnect = async () => {
    const r = await actionGetOauthUrl(destinationId);
    if (r.ok && r.url) window.location.assign(r.url);
    else alert(r.ok ? "Không lấy được link OAuth" : r.error);
  };

  const s = data?.summary ?? {};
  const cards = useMemo(
    () => [
      { label: "Views", value: (s.views ?? 0).toLocaleString() },
      { label: "Watch time", value: `${s.watch_hours ?? 0}h` },
      { label: "Avg view duration", value: `${s.avg_view_duration ?? 0}s` },
      { label: "Subscribers net", value: `${(s.subs_net ?? 0) >= 0 ? "+" : ""}${s.subs_net ?? 0}` },
    ],
    [s],
  );

  return (
    <div className="w-full max-w-full space-y-3 overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-extrabold text-slate-900">Channel Analytics</h3>
        <div className="flex items-center gap-1.5">
          {RANGES.map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => setRange(r)}
              className={`min-h-[36px] rounded-lg px-2.5 text-[11px] font-bold transition ${
                range === r ? "bg-indigo-600 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
              }`}
            >
              {r.toUpperCase()}
            </button>
          ))}
          <button
            type="button"
            onClick={refresh}
            disabled={refreshing}
            className="min-h-[36px] rounded-lg border border-slate-200 bg-white px-2.5 text-[11px] font-bold text-slate-700 disabled:opacity-50"
          >
            {refreshing ? "…" : "Refresh"}
          </button>
        </div>
      </div>

      {notice ? <p className="rounded-lg bg-slate-50 px-3 py-2 text-[11px] font-semibold text-slate-600">{notice}</p> : null}

      {data && !data.oauth_ready ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
          <p className="font-bold">Analytics cần quyền mới (yt-analytics.readonly).</p>
          <p className="mt-0.5">Token hiện tại thiếu scope — kênh vẫn hoạt động bình thường, chỉ thiếu tab này.</p>
          {data.reconnect_required ? (
            <button
              type="button"
              onClick={reconnect}
              className="mt-2 rounded-lg bg-amber-600 px-3 py-1.5 text-[11px] font-bold text-white"
            >
              Reconnect OAuth
            </button>
          ) : null}
        </div>
      ) : null}

      {loading && !data ? (
        <p className="py-6 text-center text-xs text-slate-400">Đang tải analytics…</p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {cards.map((c) => (
              <div key={c.label} className="rounded-xl border border-slate-200 bg-white p-3">
                <p className="text-[10px] font-bold uppercase tracking-wide text-slate-400">{c.label}</p>
                <p className="mt-0.5 truncate text-base font-black text-slate-900">{c.value}</p>
              </div>
            ))}
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-3">
            <p className="text-[11px] font-extrabold text-slate-700">Views over time</p>
            <LineChart points={(data?.daily ?? []).map((d) => d.views)} color="#4f46e5" />
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-3">
            <p className="text-[11px] font-extrabold text-slate-700">Watch time (minutes)</p>
            <LineChart points={(data?.daily ?? []).map((d) => d.watch_minutes)} color="#059669" />
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-3">
            <p className="text-[11px] font-extrabold text-slate-700">Subscribers gained / lost</p>
            <BarList
              rows={[
                { label: "Gained", value: s.subs_gained ?? 0 },
                { label: "Lost", value: s.subs_lost ?? 0 },
              ]}
            />
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-3">
            <p className="text-[11px] font-extrabold text-slate-700">Traffic sources</p>
            {data && data.traffic_sources.length > 0 ? (
              <BarList rows={data.traffic_sources.map((t) => ({ label: t.source, value: t.views }))} />
            ) : (
              <p className="mt-1 text-[11px] text-slate-400">Chưa có dữ liệu — bấm Refresh.</p>
            )}
          </div>

          {(data?.search_terms?.length ?? 0) > 0 ? (
            <div className="rounded-xl border border-slate-200 bg-white p-3">
              <p className="text-[11px] font-extrabold text-slate-700">Top YouTube search terms (thật)</p>
              <BarList rows={(data?.search_terms ?? []).map((t) => ({ label: t.term, value: t.views }))} />
            </div>
          ) : null}

          <div className="rounded-xl border border-slate-200 bg-white p-3">
            <p className="text-[11px] font-extrabold text-slate-700">Top videos</p>
            <div className="mt-2 space-y-2">
              {(data?.top_videos ?? []).slice(0, 10).map((v) => (
                <div key={v.video_id} className="flex items-center gap-2.5">
                  {v.thumbnail ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={v.thumbnail} alt="" className="h-10 w-16 shrink-0 rounded-md bg-slate-900 object-cover" />
                  ) : (
                    <div className="h-10 w-16 shrink-0 rounded-md bg-slate-200" />
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-bold text-slate-900">{v.title || v.video_id}</p>
                    <p className="text-[10px] text-slate-500">
                      {v.views.toLocaleString()} views · {Math.round(v.watch_minutes)}m watch · {v.avg_view_duration}s avg · +
                      {v.subs_gained} subs
                    </p>
                  </div>
                  <a
                    href={`https://youtu.be/${v.video_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="shrink-0 text-[11px] font-bold text-indigo-600"
                  >
                    ↗
                  </a>
                </div>
              ))}
              {(data?.top_videos?.length ?? 0) === 0 ? (
                <p className="text-[11px] text-slate-400">Chưa có dữ liệu — bấm Refresh.</p>
              ) : null}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
