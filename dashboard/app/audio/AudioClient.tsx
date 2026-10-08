"use client";

import Link from "next/link";
import { useState } from "react";
import type { AudioPipelineDto } from "@/lib/audio-api";

export function AudioPipelineList({
  pipelines, error,
}: {
  pipelines: AudioPipelineDto[];
  error: string | null;
}) {
  const [deleting, setDeleting] = useState<string | null>(null);
  const [items, setItems] = useState(pipelines);

  async function handleDelete(id: string, name: string) {
    if (!window.confirm(`Xóa pipeline "${name}" và toàn bộ dữ liệu?`)) return;
    setDeleting(id);
    try {
      const res = await fetch(`/api/audio/pipelines/${encodeURIComponent(id)}`,
        { method: "DELETE" });
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

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-extrabold text-slate-900">Audio Pipelines</h1>
        <Link
          href="/audio/new"
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
      {items.length === 0 && !error ? (
        <p className="rounded-2xl bg-white px-4 py-6 text-center text-sm text-slate-500">
          Chưa có pipeline nào.
        </p>
      ) : null}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {items.map((p) => (
          <div key={p.id} className="rounded-2xl bg-white p-4 shadow-sm">
            <div className="flex items-start justify-between gap-2">
              <Link href={`/audio/${encodeURIComponent(p.id)}`}
                className="min-w-0 text-sm font-extrabold text-slate-900 hover:text-indigo-700">
                <span className="block truncate">{p.name}</span>
              </Link>
              <button
                type="button"
                onClick={() => void toggle(p.id, p.enabled)}
                className={`shrink-0 rounded-full px-2.5 py-1 text-[11px] font-bold ${
                  p.enabled ? "bg-emerald-100 text-emerald-700" : "bg-slate-200 text-slate-600"
                }`}
              >
                {p.enabled ? "Bật" : "Tắt"}
              </button>
            </div>
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
            <div className="mt-3 flex gap-2">
              <Link
                href={`/audio/${encodeURIComponent(p.id)}`}
                className="inline-flex min-h-[40px] flex-1 items-center justify-center rounded-xl bg-slate-900 px-3 text-xs font-bold text-white"
              >
                Mở pipeline
              </Link>
              <button
                type="button"
                onClick={() => void handleDelete(p.id, p.name)}
                disabled={deleting === p.id}
                className="inline-flex min-h-[40px] items-center rounded-xl border border-rose-200 px-3 text-xs font-bold text-rose-600 disabled:opacity-50"
              >
                Xóa
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
