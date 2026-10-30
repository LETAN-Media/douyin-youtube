"use client";

import { useState } from "react";
import { RefreshCw, Search, Trash2 } from "lucide-react";

import type { YtFbPipeline } from "@/lib/youtube-fb-api";

interface Props {
  initialPipelines: YtFbPipeline[];
}

export function YouTubeFbPipelineList({ initialPipelines }: Props) {
  const [pipelines, setPipelines] = useState<YtFbPipeline[]>(initialPipelines);
  const [search, setSearch] = useState("");

  const filtered = pipelines.filter((p) => p.name.toLowerCase().includes(search.toLowerCase()));

  if (pipelines.length === 0) {
    return (
      <div className="p-6 text-center text-slate-500">
        Chưa có pipeline nào. Tạo pipeline đầu tiên để bắt đầu.
      </div>
    );
  }

  return (
    <div className="p-4">
      <div className="mb-4 flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <input
            type="text"
            placeholder="Tìm pipeline..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-lg border border-slate-300 pl-9 pr-3 py-2 text-sm"
          />
        </div>
        <button
          type="button"
          onClick={async () => {
            const res = await fetch("/api/youtube-fb/pipelines", { method: "GET", cache: "no-store" });
            if (res.ok) setPipelines(await res.json());
          }}
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium hover:bg-slate-100"
        >
          <RefreshCw className="h-4 w-4" /> Làm mới
        </button>
      </div>
      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50">
            <tr>
              <th className="px-4 py-2.5 font-medium text-slate-600">Tên pipeline</th>
              <th className="px-4 py-2.5 font-medium text-slate-600">Trạng thái</th>
              <th className="px-4 py-2.5 font-medium text-slate-600">Video</th>
              <th className="px-4 py-2.5 font-medium text-slate-600">AI</th>
              <th className="px-4 py-2.5 font-medium text-slate-600 text-right">Thao tác</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((p) => (
              <tr key={p.id} className="border-t border-slate-100 hover:bg-slate-50">
                <td className="px-4 py-2.5">
                  <a href={`/youtube-fb/${p.id}`} className="font-medium text-slate-800 hover:underline">
                    {p.name}
                  </a>
                </td>
                <td className="px-4 py-2.5">
                  <span
                    className={
                      p.status === "active"
                        ? "inline-flex rounded-full px-2 py-0.5 text-xs font-medium text-green-700 bg-green-50"
                        : p.status === "paused"
                        ? "inline-flex rounded-full px-2 py-0.5 text-xs font-medium text-amber-700 bg-amber-50"
                        : "inline-flex rounded-full px-2 py-0.5 text-xs font-medium text-slate-700 bg-slate-100"
                    }
                  >
                    {p.status === "active" ? "Hoạt động" : p.status === "paused" ? "Tạm dừng" : p.status}
                  </span>
                </td>
                <td className="px-4 py-2.5 text-slate-600">{p.video_count ?? "-"}</td>
                <td className="px-4 py-2.5 text-slate-600">{p.ai_strategy === "off" ? "Tắt" : "Bật"}</td>
                <td className="px-4 py-2.5 text-right">
                  <button
                    type="button"
                    onClick={async () => {
                      if (!confirm(`Xóa pipeline "${p.name}"?`)) return;
                      const res = await fetch(`/api/youtube-fb/pipelines/${p.id}`, { method: "DELETE" });
                      if (res.ok) setPipelines(pipelines.filter((x) => x.id !== p.id));
                    }}
                    className="inline-flex items-center justify-center rounded-lg border border-slate-300 px-2 py-1 text-slate-600 hover:bg-slate-100"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
