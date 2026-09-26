"use client";

import { useCallback, useEffect, useState } from "react";
import type { UpcomingItem } from "@/lib/types";

interface Props {
  destinationId: string;
}

export function UpcomingScheduled({ destinationId }: Props) {
  const [items, setItems] = useState<UpcomingItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [editId, setEditId] = useState<string | null>(null);
  const [editDate, setEditDate] = useState("");
  const [editTime, setEditTime] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/channels/${destinationId}/upcoming`);
      if (res.ok) {
        const data = await res.json();
        setItems(Array.isArray(data.items) ? data.items : []);
      }
    } catch {
      /* noop */
    } finally {
      setLoading(false);
    }
  }, [destinationId]);

  useEffect(() => {
    load();
  }, [load]);

  const act = async (pubId: string, action: "publish-now" | "cancel-schedule") => {
    setBusyId(pubId);
    try {
      const res = await fetch(`/api/publications/${pubId}/${action}`, { method: "POST" });
      if (!res.ok) {
        const e = await res.json().catch(() => ({}));
        alert(e.detail || e.error || "Thao tác thất bại");
      }
      await load();
    } finally {
      setBusyId(null);
    }
  };

  const saveTime = async (pubId: string) => {
    if (!editDate || !editTime) {
      alert("Chọn ngày + giờ mới");
      return;
    }
    setBusyId(pubId);
    try {
      const res = await fetch(`/api/publications/${pubId}/schedule`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ publish_date: editDate, publish_time: editTime }),
      });
      if (!res.ok) {
        const e = await res.json().catch(() => ({}));
        alert(e.detail || "Đổi lịch thất bại");
      } else {
        setEditId(null);
        await load();
      }
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="w-full max-w-full overflow-hidden rounded-2xl border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
          Upcoming / Scheduled ({items.length})
        </p>
        <button
          type="button"
          onClick={load}
          className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-[11px] font-bold text-slate-600 hover:bg-slate-50"
        >
          {loading ? "…" : "Refresh"}
        </button>
      </div>
      {items.length === 0 ? (
        <p className="mt-3 text-xs text-slate-400">
          {loading ? "Đang tải…" : "Chưa có video nào lên lịch."}
        </p>
      ) : (
        <div className="mt-3 space-y-2.5">
          {items.map((it) => (
            <div
              key={it.publication_id}
              className="flex flex-col gap-2 rounded-xl border border-slate-100 bg-slate-50/60 p-3 sm:flex-row sm:items-center"
            >
              {it.thumbnail ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={it.thumbnail}
                  alt=""
                  className="h-16 w-12 shrink-0 rounded-lg bg-slate-900 object-cover"
                />
              ) : null}
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-bold text-slate-900">
                  {it.video_title || it.youtube_video_id || it.publication_id}
                </p>
                <p className="truncate text-[11px] text-slate-500">
                  {it.preview || it.youtube_publish_at || it.status}
                  {it.youtube_schedule_timezone ? ` · ${it.youtube_schedule_timezone}` : ""}
                </p>
                {it.youtube_video_id ? (
                  <p className="truncate font-mono text-[10px] text-slate-400">
                    {it.youtube_video_id}
                  </p>
                ) : null}
                {editId === it.publication_id ? (
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <input
                      type="date"
                      value={editDate}
                      onChange={(e) => setEditDate(e.target.value)}
                      className="min-w-0 flex-1 rounded-lg border border-slate-200 px-2 py-1.5 text-xs"
                    />
                    <input
                      type="time"
                      value={editTime}
                      onChange={(e) => setEditTime(e.target.value)}
                      className="w-24 rounded-lg border border-slate-200 px-2 py-1.5 text-xs"
                    />
                    <button
                      type="button"
                      disabled={busyId === it.publication_id}
                      onClick={() => saveTime(it.publication_id)}
                      className="rounded-lg bg-indigo-600 px-2.5 py-1.5 text-[11px] font-bold text-white"
                    >
                      Save
                    </button>
                  </div>
                ) : null}
              </div>
              <div className="flex shrink-0 flex-wrap items-center gap-1.5">
                {it.external_url ? (
                  <a
                    href={it.external_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-[11px] font-bold text-slate-700"
                  >
                    Open ↗
                  </a>
                ) : null}
                <button
                  type="button"
                  onClick={() =>
                    editId === it.publication_id ? setEditId(null) : setEditId(it.publication_id)
                  }
                  className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-[11px] font-bold text-slate-700"
                >
                  Change time
                </button>
                <button
                  type="button"
                  disabled={busyId === it.publication_id}
                  onClick={() => act(it.publication_id, "publish-now")}
                  className="rounded-lg bg-emerald-600 px-2 py-1.5 text-[11px] font-bold text-white"
                >
                  Publish now
                </button>
                <button
                  type="button"
                  disabled={busyId === it.publication_id}
                  onClick={() => act(it.publication_id, "cancel-schedule")}
                  className="rounded-lg border border-rose-200 bg-white px-2 py-1.5 text-[11px] font-bold text-rose-700"
                >
                  Cancel
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
