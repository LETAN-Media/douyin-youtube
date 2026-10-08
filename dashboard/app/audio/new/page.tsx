"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Shell } from "@/components/Shell";

export default function NewAudioPipelinePage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleCreate() {
    if (!name.trim() || saving) return;
    setSaving(true);
    setError(null);
    try {
      const res = await fetch("/api/audio/pipelines", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim() }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.message || data.error || "Tạo thất bại.");
      router.push(`/audio/${encodeURIComponent(data.id)}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Tạo thất bại.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Shell>
    <div className="mx-auto max-w-xl space-y-4 p-4">
      <h1 className="text-lg font-extrabold text-slate-900">Tạo Audio Pipeline</h1>
      <div className="rounded-2xl bg-white p-4 shadow-sm">
        <label className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
          Tên pipeline
        </label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="VD: Audio Ngôn Tình"
          className="mt-2 block min-h-[44px] w-full rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none focus:border-indigo-500"
        />
        {error ? (
          <p className="mt-2 text-xs font-semibold text-rose-600">{error}</p>
        ) : null}
        <button
          type="button"
          onClick={() => void handleCreate()}
          disabled={saving || !name.trim()}
          className="mt-3 inline-flex min-h-[44px] items-center rounded-2xl bg-indigo-600 px-5 py-2 text-sm font-bold text-white disabled:opacity-50"
        >
          {saving ? "Đang tạo…" : "Tạo pipeline"}
        </button>
      </div>
    </div>
    </Shell>
  );
}
