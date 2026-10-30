"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { Play, Pause, RefreshCw, Trash2, Scan } from "lucide-react";

import type {
  YtFbFacebookPage,
  YtFbPipeline,
  YtFbQueueItem,
  YtFbPublication,
  YtFbSchedule,
  YtFbSource,
  YtFbVideo,
} from "@/lib/youtube-fb-api";

function Tab({ label, value, active, setActive }: {
  label: string; value: string; active: boolean; setActive: (v: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => setActive(value)}
      className={
        "px-4 py-2 text-sm font-medium " +
        (active ? "border-b-2 border-blue-600 text-blue-700" : "text-slate-600 hover:text-slate-800")
      }
    >
      {label}
    </button>
  );
}

export function YouTubeFbPipelineDetail({
  initialPipeline,
  initialSources,
  initialVideos,
  initialQueue,
  initialHistory,
  initialPages,
  initialSchedules,
}: {
  initialPipeline: YtFbPipeline;
  initialSources: YtFbSource[];
  initialVideos: YtFbVideo[];
  initialQueue: YtFbQueueItem[];
  initialHistory: YtFbPublication[];
  initialPages: YtFbFacebookPage[];
  initialSchedules: YtFbSchedule[];
}) {
  const [pipeline, setPipeline] = useState(initialPipeline);
  const [active, setActive] = useState("overview");
  const [sources, setSources] = useState(initialSources);
  const [videos, setVideos] = useState(initialVideos);
  const [queue, setQueue] = useState(initialQueue);
  const [history, setHistory] = useState(initialHistory);
  const [pages, setPages] = useState(initialPages);
  const [schedules, setSchedules] = useState(initialSchedules);

  async function togglePublish() {
    const res = await fetch(`/api/youtube-fb/pipelines/${pipeline.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: pipeline.status === "active" ? "paused" : "active" }),
    });
    if (res.ok) setPipeline(await res.json());
  }

  async function scanNow() {
    const res = await fetch(`/api/youtube-fb/pipelines/${pipeline.id}/scan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    if (res.ok) {
      const data = await res.json();
      alert(`Đã quét: ${data.scanned} mới`);
    }
  }

  const tabs: { value: string; label: string }[] = [
    { value: "overview", label: "Tổng quan" },
    { value: "sources", label: "Nguồn" },
    { value: "inventory", label: "Video" },
    { value: "queue", label: "Hàng đợi" },
    { value: "schedule", label: "Lịch" },
    { value: "pages", label: "Fanpage" },
    { value: "ai", label: "AI" },
    { value: "settings", label: "Cài đặt" },
    { value: "history", label: "Lịch sử" },
  ];

  return (
    <div className="flex flex-col">
      <div className="flex items-center justify-between border-b border-slate-200 px-6 py-3">
        <h1 className="text-xl font-semibold">{pipeline.name}</h1>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={scanNow}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium hover:bg-slate-100"
          >
            <Scan className="h-4 w-4" /> Quét ngay
          </button>
          <button
            type="button"
            onClick={togglePublish}
            className={
              "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium " +
              (pipeline.auto_publish
                ? "bg-green-600 text-white hover:bg-green-700"
                : "border border-slate-300 text-slate-700 hover:bg-slate-100")
            }
          >
            {pipeline.auto_publish ? <Play className="h-4 w-4" /> : <Pause className="h-4 w-4" />}
            {pipeline.auto_publish ? "Đang xuất bản" : "Tạm dừng"}
          </button>
          <Link
            href="/youtube-fb/manual"
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium hover:bg-slate-100"
          >
            + Đăng tay
          </Link>
        </div>
      </div>
      <div className="border-b border-slate-200">
        {tabs.map((t) => (
          <Tab key={t.value} label={t.label} value={t.value} active={active === t.value} setActive={setActive} />
        ))}
      </div>
      <div className="p-6">
        {active === "overview" && (
          <div className="space-y-2 text-sm">
            <p><span className="font-medium text-slate-600">Trạng thái:</span> {pipeline.status}</p>
            <p><span className="font-medium text-slate-600">YouTube kênh:</span> {pipeline.youtube_channel_id || pipeline.youtube_channel_title || "Chưa cấu hình"}</p>
            <p><span className="font-medium text-slate-600">Video:</span> {pipeline.video_count ?? "-"}</p>
            <p><span className="font-medium text-slate-600">AI:</span> {pipeline.ai_strategy === "off" ? "Tắt" : "Bật"} ({pipeline.ai_model || "mặc định"})</p>
            <p><span className="font-medium text-slate-600">Xuất bản tự động:</span> {pipeline.auto_publish ? "Bật" : "Tắt"} | Tối đa/ngày: {pipeline.max_daily_publish}</p>
          </div>
        )}
        {active === "sources" && (
          <div className="space-y-2">
            <div className="flex justify-between items-center">
              <span className="text-sm text-slate-600">Nguồn YouTube (kênh hoặc playlist)</span>
              <Link href={`/youtube-fb/${pipeline.id}/sources/new`} className="text-sm text-blue-600 hover:underline">Thêm nguồn</Link>
            </div>
            <table className="w-full text-sm">
              <thead><tr><th className="text-left py-1 text-slate-600">ID</th><th className="text-left py-1 text-slate-600">Loại</th><th className="text-left py-1 text-slate-600">Kênh/Playlist</th><th className="text-left py-1 text-slate-600">Trạng thái</th></tr></thead>
              <tbody>
                {sources.length === 0 && <tr><td colSpan={4} className="py-3 text-slate-500">Chưa có nguồn.</td></tr>}
                {sources.map((s) => (
                  <tr key={s.id} className="border-t">
                    <td className="py-2">{s.id}</td>
                    <td className="py-2">{s.source_type}</td>
                    <td className="py-2">{s.channel_title || s.custom_url || "-"}</td>
                    <td className="py-2">{s.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {active === "inventory" && (
          <div>
            <p className="mb-2 text-sm text-slate-600">Tổng video đã lưu: {videos.length}</p>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr><th className="text-left py-1 text-slate-600">Video ID</th><th className="text-left py-1 text-slate-600">Tiêu đề</th><th className="text-left py-1 text-slate-600">Thời lượng (s)</th></tr></thead>
                <tbody>
                  {videos.map((v) => (
                    <tr key={v.video_id} className="border-t">
                      <td className="py-1.5">{v.video_id}</td>
                      <td className="py-1.5">{v.title || "-"}</td>
                      <td className="py-1.5">{v.duration_seconds ?? "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
        {active === "queue" && (
          <div>
            <p className="mb-2 text-sm text-slate-600">Hàng đợi ({queue.length})</p>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr><th className="text-left py-1 text-slate-600">Video</th><th className="text-left py-1 text-slate-600">Trạng thái</th><th className="text-left py-1 text-slate-600">Lịch xuất bản</th><th className="text-left py-1 text-slate-600">AI</th></tr></thead>
                <tbody>
                  {queue.map((q) => (
                    <tr key={q.id} className="border-t">
                      <td className="py-1.5">{q.youtube_video_id}</td>
                      <td className="py-1.5">{q.status}</td>
                      <td className="py-1.5">{q.scheduled_for || "ngay"}</td>
                      <td className="py-1.5">{q.ai_caption ? "Có" : "Chưa"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
        {active === "schedule" && (
          <div>
            <p className="mb-2 text-sm text-slate-600">Lịch xuất bản ({schedules.length} slot)</p>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr><th className="text-left py-1 text-slate-600">Ngày</th><th className="text-left py-1 text-slate-600">Slot</th><th className="text-left py-1 text-slate-600">Giờ</th><th className="text-left py-1 text-slate-600">Đã xuất bản</th></tr></thead>
                <tbody>
                  {schedules.map((s) => (
                    <tr key={s.id} className="border-t">
                      <td className="py-1.5">{s.scheduled_date}</td>
                      <td className="py-1.5">{s.slot_index}</td>
                      <td className="py-1.5">{s.slot_time}</td>
                      <td className="py-1.5">{s.publish_count}/{s.slot_max_daily}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
        {active === "pages" && (
          <div className="space-y-2">
            <div className="flex justify-between">
              <span className="text-sm text-slate-600">Fanpage Facebook ({pages.length})</span>
              <Link href={`/youtube-fb/${pipeline.id}/pages/new`} className="text-sm text-blue-600 hover:underline">Thêm fanpage</Link>
            </div>
            <table className="w-full text-sm">
              <thead><tr><th className="text-left py-1 text-slate-600">Page ID</th><th className="text-left py-1 text-slate-600">Tên</th><th className="text-left py-1 text-slate-600">Mặc định</th><th className="text-left py-1 text-slate-600">Trạng thái</th></tr></thead>
              <tbody>
                {pages.map((pg) => (
                  <tr key={pg.id} className="border-t">
                    <td className="py-1.5">{pg.page_id}</td>
                    <td className="py-1.5">{pg.page_name || "-"}</td>
                    <td className="py-1.5">{pg.is_default ? "✓" : ""}</td>
                    <td className="py-1.5">{pg.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {active === "ai" && (
          <div className="space-y-2 text-sm">
            <p><span className="font-medium text-slate-600">Chiến lược AI:</span> {pipeline.ai_strategy}</p>
            <p><span className="font-medium text-slate-600">Mô hình:</span> {pipeline.ai_model || "Mặc định"}</p>
            <p><span className="font-medium text-slate-600">Max tokens:</span> {pipeline.ai_max_tokens ?? "-"}</p>
            <p className="text-slate-500">Cài đặt AI được quản lý qua backend ToolNet.</p>
          </div>
        )}
        {active === "settings" && (
          <div className="space-y-2 text-sm">
            <p><span className="font-medium text-slate-600">Đặt lịch tự động:</span> {pipeline.auto_scan ? "Bật" : "Tắt"}</p>
            <p><span className="font-medium text-slate-600">Slot/ngày:</span> {pipeline.slot_max_daily}</p>
            <p><span className="font-medium text-slate-600">Khoảng cách tối thiểu:</span> {pipeline.min_interval_minutes} phút</p>
          </div>
        )}
        {active === "history" && (
          <div>
            <p className="mb-2 text-sm text-slate-600">Lịch sử xuất bản ({history.length})</p>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr><th className="text-left py-1 text-slate-600">Video</th><th className="text-left py-1 text-slate-600">Fanpage</th><th className="text-left py-1 text-slate-600">Trạng thái</th><th className="text-left py-1 text-slate-600">Ngày</th></tr></thead>
                <tbody>
                  {history.map((h) => (
                    <tr key={h.id} className="border-t">
                      <td className="py-1.5">{h.youtube_video_id}</td>
                      <td className="py-1.5">{h.facebook_page_id}</td>
                      <td className="py-1.5">{h.status}</td>
                      <td className="py-1.5">{h.published_at || h.created_at}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
