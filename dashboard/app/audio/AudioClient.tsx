"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import type { AudioPipelineDto } from "@/lib/audio-api";

export function AudioPipelineList({
  pipelines,
  error,
}: {
  pipelines: AudioPipelineDto[];
  error: string | null;
}) {
  const searchParams = useSearchParams();
  const [activeTab, setActiveTab] = useState<"auto" | "manual">(() => {
    if (typeof window !== "undefined") {
      const sp = new URLSearchParams(window.location.search);
      const tabParam = sp.get("tab");
      if (tabParam === "manual") return "manual";
      if (tabParam === "auto") return "auto";
      try {
        const saved = sessionStorage.getItem("audio_active_tab");
        if (saved === "manual") return "manual";
      } catch {
        // ignore
      }
    }
    return "auto";
  });

  const [deleting, setDeleting] = useState<string | null>(null);
  const [items, setItems] = useState(pipelines);

  // Sync tab from searchParams if query changes (e.g. back/forward navigation)
  useEffect(() => {
    const tabParam = searchParams.get("tab");
    if (tabParam === "manual" || tabParam === "auto") {
      setActiveTab(tabParam);
      try {
        sessionStorage.setItem("audio_active_tab", tabParam);
      } catch {
        // ignore
      }
    }
  }, [searchParams]);

  function switchTab(nextTab: "auto" | "manual") {
    setActiveTab(nextTab);
    const url = nextTab === "manual" ? "/audio?tab=manual" : "/audio";
    window.history.replaceState(null, "", url);
    try {
      sessionStorage.setItem("audio_active_tab", nextTab);
    } catch {
      // ignore
    }
  }

  async function handleDelete(id: string, name: string) {
    if (!window.confirm(`Xóa pipeline "${name}" và toàn bộ dữ liệu?`)) return;
    setDeleting(id);
    try {
      const res = await fetch(`/api/audio/pipelines/${encodeURIComponent(id)}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error("Delete failed");
      setItems((prev) => prev.filter((p) => p.id !== id));
    } catch {
      alert("Không xóa được pipeline.");
    } finally {
      setDeleting(null);
    }
  }

  async function toggle(id: string, enabled: boolean) {
    const res = await fetch(`/api/audio/pipelines/${encodeURIComponent(id)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !enabled }),
    });
    if (res.ok) {
      const updated = (await res.json()) as AudioPipelineDto;
      setItems((prev) => prev.map((p) => (p.id === id ? updated : p)));
    }
  }

  const displayedItems = items.filter((p) => {
    if (activeTab === "manual") {
      return p.pipeline_type === "manual";
    }
    return p.pipeline_type !== "manual";
  });

  return (
    <div className="space-y-4">
      {/* Header with Title, Tabs, and Create button */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-extrabold text-slate-900">Audio Pipelines</h1>
          {/* Tabs: [ Tự Động ] [ Thủ Công ] */}
          <div className="mt-2 inline-flex rounded-xl bg-slate-100 p-1">
            <button
              type="button"
              onClick={() => switchTab("auto")}
              className={`inline-flex min-h-[36px] items-center rounded-lg px-4 py-1.5 text-xs font-bold transition-all ${
                activeTab === "auto"
                  ? "bg-white text-slate-900 shadow-sm"
                  : "text-slate-600 hover:text-slate-900"
              }`}
            >
              Tự Động
            </button>
            <button
              type="button"
              onClick={() => switchTab("manual")}
              className={`inline-flex min-h-[36px] items-center rounded-lg px-4 py-1.5 text-xs font-bold transition-all ${
                activeTab === "manual"
                  ? "bg-white text-slate-900 shadow-sm"
                  : "text-slate-600 hover:text-slate-900"
              }`}
            >
              Thủ Công
            </button>
          </div>
        </div>

        <Link
          href={activeTab === "manual" ? "/audio/new?type=manual" : "/audio/new"}
          className="inline-flex min-h-[44px] items-center rounded-2xl bg-indigo-600 px-4 py-2 text-sm font-bold text-white hover:bg-indigo-500"
        >
          + Tạo pipeline
        </Link>
      </div>

      {error ? (
        <p className="rounded-2xl bg-rose-50 px-4 py-3 text-sm font-semibold text-rose-700">
          {error}
        </p>
      ) : null}

      {/* Empty State */}
      {displayedItems.length === 0 && !error ? (
        <div className="rounded-2xl bg-white px-4 py-8 text-center shadow-sm">
          <p className="text-sm font-medium text-slate-500">
            {activeTab === "manual"
              ? "Chưa có pipeline thủ công nào."
              : "Chưa có pipeline tự động nào."}
          </p>
          <Link
            href={activeTab === "manual" ? "/audio/new?type=manual" : "/audio/new"}
            className="mt-3 inline-flex min-h-[40px] items-center rounded-xl bg-indigo-600 px-4 py-2 text-xs font-bold text-white hover:bg-indigo-500"
          >
            {activeTab === "manual" ? "+ Tạo pipeline thủ công" : "+ Tạo pipeline"}
          </Link>
        </div>
      ) : null}

      {/* Pipeline Cards Grid */}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {displayedItems.map((p) => {
          const isManual = p.pipeline_type === "manual";
          const linkHref = isManual
            ? `/audio/${encodeURIComponent(p.id)}?tab=manual`
            : `/audio/${encodeURIComponent(p.id)}`;

          return (
            <div key={p.id} className="rounded-2xl bg-white p-4 shadow-sm">
              <div className="flex items-start justify-between gap-2">
                <Link
                  href={linkHref}
                  className="min-w-0 text-sm font-extrabold text-slate-900 hover:text-indigo-700"
                >
                  <span className="block truncate">{p.name}</span>
                </Link>

                <div className="flex shrink-0 items-center gap-1.5">
                  {isManual ? (
                    <span className="rounded-full bg-amber-100 px-2.5 py-1 text-[11px] font-bold text-amber-800">
                      Thủ Công
                    </span>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => void toggle(p.id, p.enabled)}
                    className={`rounded-full px-2.5 py-1 text-[11px] font-bold ${
                      p.enabled
                        ? "bg-emerald-100 text-emerald-700"
                        : "bg-slate-200 text-slate-600"
                    }`}
                  >
                    {p.enabled ? "Bật" : "Tắt"}
                  </button>
                </div>
              </div>

              {/* Stat grid */}
              {isManual ? (
                <div className="mt-2 grid grid-cols-2 gap-2 text-center">
                  {[
                    ["Chờ đăng", p.pending_videos],
                    ["Đã đăng", p.published_videos],
                    ["Đang chạy", p.running_jobs],
                    ["Job lỗi", p.failed_jobs],
                  ].map(([label, value]) => (
                    <div key={label} className="rounded-xl bg-slate-50 px-2 py-1.5">
                      <p className="text-sm font-extrabold text-slate-900">{value}</p>
                      <p className="text-[11px] text-slate-500">{label}</p>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="mt-2 grid grid-cols-3 gap-2 text-center">
                  {[
                    ["Nguồn", p.total_sources],
                    ["Chờ đăng", p.pending_videos],
                    ["Đã đăng", p.published_videos],
                    ["Đang chạy", p.running_jobs],
                    ["Job lỗi", p.failed_jobs],
                    ["Auto", p.auto_publish ? "ON" : "OFF"],
                  ].map(([label, value]) => (
                    <div key={label} className="rounded-xl bg-slate-50 px-2 py-1.5">
                      <p className="text-sm font-extrabold text-slate-900">{value}</p>
                      <p className="text-[11px] text-slate-500">{label}</p>
                    </div>
                  ))}
                </div>
              )}

              {/* Actions */}
              <div className="mt-3 flex gap-2">
                <Link
                  href={linkHref}
                  className="inline-flex min-h-[40px] flex-1 items-center justify-center rounded-xl bg-slate-900 px-3 text-xs font-bold text-white hover:bg-slate-800"
                >
                  Mở pipeline
                </Link>
                <button
                  type="button"
                  onClick={() => void handleDelete(p.id, p.name)}
                  disabled={deleting === p.id}
                  className="inline-flex min-h-[40px] items-center rounded-xl border border-rose-200 px-3 text-xs font-bold text-rose-600 hover:bg-rose-50 disabled:opacity-50"
                >
                  Xóa
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
