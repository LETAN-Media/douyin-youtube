"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { ytFb, type YtFbPipelineCreate } from "@/lib/youtube-fb-api";

export function YouTubeFbCreateForm() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [timezone, setTimezone] = useState("Asia/Ho_Chi_Minh");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    const payload: YtFbPipelineCreate = {
      name: name.trim(),
      description: description || undefined,
      timezone,
      publish_slots: ["09:00", "15:00"],
      slot_max_daily: 5,
      min_interval_minutes: 60,
      auto_scan: true,
      auto_publish: true,
      ai_strategy: "auto",
      default_publish_mode: "reels_or_video",
    };
    try {
      const res = await fetch("/api/youtube-fb/pipelines", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(await res.text());
      const created = await res.json();
      router.push(`/youtube-fb/${created.id}`);
    } catch (err: any) {
      setError(err?.message || "Tạo pipeline thất bại.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="max-w-md space-y-4">
      <div>
        <label className="block text-sm font-medium text-slate-700">Tên pipeline</label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
        />
      </div>
      <div>
        <label className="block text-sm font-medium text-slate-700">Mô tả</label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          rows={3}
        />
      </div>
      <div>
        <label className="block text-sm font-medium text-slate-700">Múi giờ</label>
        <input
          type="text"
          value={timezone}
          onChange={(e) => setTimezone(e.target.value)}
          className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
        />
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <button
        type="submit"
        disabled={loading}
        className="w-full rounded-lg bg-blue-600 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
      >
        {loading ? "Đang tạo..." : "Tạo pipeline"}
      </button>
    </form>
  );
}

void ytFb;
