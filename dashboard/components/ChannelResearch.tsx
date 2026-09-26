"use client";

import { useCallback, useEffect, useState } from "react";

interface TrendVideo {
  video_id: string;
  title?: string | null;
  channel_title?: string | null;
  thumbnail_url?: string | null;
  views: number;
  views_per_hour: number;
  age_hours?: number | null;
  trend_score: number;
  channel_fit_score?: number | null;
  evidence: Record<string, unknown>;
}

interface HashtagItem {
  tag: string;
  trend_score: number;
  channel_fit_score?: number | null;
  evidence: Record<string, unknown>;
}

interface ResearchData {
  status: string;
  run?: {
    id: string;
    status: string;
    region: string;
    search_calls_used: number;
    videos_analyzed: number;
    error?: string | null;
    created_at?: string | null;
  } | null;
  videos: TrendVideo[];
  hashtags: HashtagItem[];
  ai?: Record<string, unknown> | null;
  niche?: Record<string, unknown> | null;
}

function ScoreBadge({ score, label }: { score?: number | null; label: string }) {
  if (score == null) return null;
  const tone = score >= 70 ? "bg-emerald-50 text-emerald-700 border-emerald-200" : score >= 45 ? "bg-amber-50 text-amber-700 border-amber-200" : "bg-slate-100 text-slate-600 border-slate-200";
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-black ${tone}`}>
      {label}: {score}
    </span>
  );
}

export function ChannelResearch({
  destinationId,
  onApply,
}: {
  destinationId: string;
  onApply: (bundle: { title?: string; keywords?: string[]; hashtags?: string[] }) => void;
}) {
  const [data, setData] = useState<ResearchData | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [region, setRegion] = useState("VN");
  const [titles, setTitles] = useState<Record<string, unknown>[]>([]);
  const [tags, setTags] = useState<Record<string, unknown>[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/channels/${destinationId}/research`);
      if (res.ok) setData(await res.json());
    } catch {
      /* noop */
    } finally {
      setLoading(false);
    }
  }, [destinationId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (data?.status !== "queued" && data?.status !== "fetching" && data?.status !== "scoring" && data?.status !== "ai_analysis") return;
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [data?.status, load]);

  const refresh = async (force = false) => {
    setBusy("refresh");
    setNotice(null);
    try {
      const res = await fetch(`/api/channels/${destinationId}/research/refresh${force ? "?force=true" : ""}`, { method: "POST" });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || "Refresh thất bại");
      if (body.cached) setNotice("Dùng cache mới nhất (chưa hết hạn). Thêm ?force để chạy lại.");
      setTimeout(load, 3000);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Refresh thất bại");
    } finally {
      setBusy(null);
    }
  };

  const genTitles = async () => {
    setBusy("titles");
    try {
      const res = await fetch(`/api/channels/${destinationId}/research/generate-titles`, { method: "POST" });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || "Tạo titles thất bại");
      setTitles(Array.isArray(body.titles) ? body.titles : []);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Tạo titles thất bại");
    } finally {
      setBusy(null);
    }
  };

  const genTags = async () => {
    setBusy("tags");
    try {
      const res = await fetch(`/api/channels/${destinationId}/research/generate-hashtags`, { method: "POST" });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || "Tạo hashtags thất bại");
      setTags(Array.isArray(body.hashtags) ? body.hashtags : []);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Tạo hashtags thất bại");
    } finally {
      setBusy(null);
    }
  };

  const applyBundle = async (bundle: Record<string, unknown>) => {
    try {
      const res = await fetch(`/api/channels/${destinationId}/research/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(bundle),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || "Apply thất bại");
      onApply({ title: body.title, keywords: body.description_keywords, hashtags: body.hashtags });
      setNotice("Đã đưa vào metadata editor — kiểm tra lại trước khi đăng.");
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Apply thất bại");
    }
  };

  const ai = (data?.ai ?? {}) as Record<string, unknown>;
  const hotTopics = (ai.hot_topics as Record<string, unknown>[] | undefined) ?? [];
  const aiTitles = (ai.title_ideas as Record<string, unknown>[] | undefined) ?? [];

  return (
    <div className="w-full max-w-full space-y-3 overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-extrabold text-slate-900">AI Research</h3>
        <div className="flex flex-wrap items-center gap-1.5">
          <select
            value={region}
            onChange={async (e) => {
              const v = e.target.value;
              setRegion(v);
              await fetch(`/api/channels/${destinationId}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ research_region: v }),
              });
            }}
            className="min-h-[36px] rounded-lg border border-slate-200 bg-white px-2 text-[11px] font-bold"
          >
            {["VN", "US", "TH", "JP", "KR", "MULTI"].map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
          <button type="button" onClick={() => refresh(false)} disabled={busy === "refresh"}
            className="min-h-[36px] rounded-lg bg-indigo-600 px-2.5 text-[11px] font-bold text-white disabled:opacity-50">
            {busy === "refresh" ? "…" : "Refresh Research"}
          </button>
        </div>
      </div>

      {notice ? <p className="rounded-lg bg-slate-50 px-3 py-2 text-[11px] font-semibold text-slate-600">{notice}</p> : null}
      {data?.run?.status === "failed" ? (
        <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[11px] font-semibold text-rose-700">
          Research failed: {data.run.error || "unknown"} — thử Refresh lại.
        </p>
      ) : null}
      {["queued", "fetching", "scoring", "ai_analysis"].includes(data?.status ?? "") || ["queued", "fetching", "scoring", "ai_analysis"].includes(data?.run?.status ?? "") ? (
        <p className="rounded-lg bg-indigo-50 px-3 py-2 text-[11px] font-bold text-indigo-700">
          Research đang chạy ({data?.run?.status ?? data?.status})… tự cập nhật.
        </p>
      ) : null}

      {loading && !data ? (
        <p className="py-6 text-center text-xs text-slate-400">Đang tải research…</p>
      ) : data?.status === "empty" ? (
        <div className="rounded-xl border border-slate-200 bg-white p-4 text-center">
          <p className="text-xs font-bold text-slate-700">Chưa có research nào.</p>
          <p className="mt-1 text-[11px] text-slate-500">Bấm Refresh Research để quét trends theo niche của kênh.</p>
          <button type="button" onClick={() => refresh(false)} className="mt-3 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-bold text-white">
            Refresh Research
          </button>
        </div>
      ) : (
        <>
          <div className="rounded-xl border border-slate-200 bg-white p-3">
            <p className="text-[11px] font-extrabold text-slate-700">Trend Radar</p>
            <div className="mt-2 space-y-2">
              {data?.videos.slice(0, 8).map((v) => (
                <div key={v.video_id} className="flex items-start gap-2.5">
                  {v.thumbnail_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={v.thumbnail_url} alt="" className="h-10 w-16 shrink-0 rounded-md bg-slate-900 object-cover" />
                  ) : (
                    <div className="h-10 w-16 shrink-0 rounded-md bg-slate-200" />
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-bold text-slate-900">{v.title || v.video_id}</p>
                    <p className="text-[10px] text-slate-500">
                      {(v.views ?? 0).toLocaleString()} views · {v.views_per_hour}/h · {v.age_hours != null ? `${Math.round(v.age_hours)}h ago` : "age?"}
                    </p>
                    <div className="mt-1 flex flex-wrap gap-1">
                      <ScoreBadge score={v.trend_score} label="Trend" />
                      <ScoreBadge score={v.channel_fit_score} label="Fit" />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {hotTopics.length > 0 ? (
            <div className="rounded-xl border border-slate-200 bg-white p-3">
              <p className="text-[11px] font-extrabold text-slate-700">Hot Topics</p>
              <ul className="mt-1.5 space-y-1 text-xs text-slate-700">
                {hotTopics.slice(0, 8).map((t, i) => (
                  <li key={i} className="rounded-lg bg-slate-50 px-2.5 py-1.5">
                    <span className="font-bold">{String(t.topic ?? "")}</span>
                    {t.why ? <span className="text-slate-500"> — {String(t.why)}</span> : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="rounded-xl border border-slate-200 bg-white p-3">
            <div className="flex items-center justify-between">
              <p className="text-[11px] font-extrabold text-slate-700">Hashtag Opportunities</p>
              <button type="button" onClick={genTags} disabled={busy === "tags"}
                className="rounded-lg border border-slate-200 px-2 py-1 text-[11px] font-bold text-slate-700 disabled:opacity-50">
                {busy === "tags" ? "…" : "Generate Hashtags"}
              </button>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {(tags.length > 0 ? tags : (data?.hashtags ?? []).slice(0, 12).map((h) => ({ tag: h.tag, why: "", channel_fit_score: h.channel_fit_score }))).map((h, i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => applyBundle({ hashtags: [String((h as Record<string, unknown>).tag ?? "")] })}
                  className="rounded-full bg-indigo-50 px-2.5 py-1 font-mono text-[11px] font-bold text-indigo-700 hover:bg-indigo-100"
                  title={String((h as Record<string, unknown>).why ?? "")}
                >
                  {String((h as Record<string, unknown>).tag ?? "")}
                </button>
              ))}
            </div>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-3">
            <div className="flex items-center justify-between">
              <p className="text-[11px] font-extrabold text-slate-700">Title Ideas</p>
              <button type="button" onClick={genTitles} disabled={busy === "titles"}
                className="rounded-lg border border-slate-200 px-2 py-1 text-[11px] font-bold text-slate-700 disabled:opacity-50">
                {busy === "titles" ? "…" : "Generate Titles"}
              </button>
            </div>
            <div className="mt-2 space-y-2">
              {(titles.length > 0 ? titles : aiTitles.slice(0, 6)).map((t, i) => {
                const item = t as Record<string, unknown>;
                return (
                  <div key={i} className="rounded-lg bg-slate-50 p-2.5">
                    <p className="text-xs font-bold text-slate-900">{String(item.title ?? "")}</p>
                    <div className="mt-1 flex flex-wrap gap-1">
                      <ScoreBadge score={item.channel_fit_score as number} label="Fit" />
                      <ScoreBadge score={item.trend_relevance_score as number} label="Trend" />
                    </div>
                    {item.reason ? <p className="mt-1 text-[10px] text-slate-500">{String(item.reason)}</p> : null}
                    <button
                      type="button"
                      onClick={() => applyBundle({ title: String(item.title ?? ""), keywords: [String(item.primary_keyword ?? "")].filter(Boolean) })}
                      className="mt-1.5 rounded-lg bg-indigo-600 px-2.5 py-1 text-[11px] font-bold text-white"
                    >
                      Apply
                    </button>
                  </div>
                );
              })}
              {titles.length === 0 && aiTitles.length === 0 ? (
                <p className="text-[11px] text-slate-400">Bấm Generate Titles để AI gợi ý theo trend + niche.</p>
              ) : null}
            </div>
          </div>

          {(data?.videos ?? []).some((v) => (v.channel_fit_score ?? 100) < 45 && v.trend_score >= 70) ? (
            <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] font-semibold text-amber-800">
              Warning: có trend nóng nhưng channel-fit thấp — hãy adapt angle theo niche trước khi đăng.
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}
