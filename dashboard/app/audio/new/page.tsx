"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Shell } from "@/components/Shell";

function NewAudioPipelineForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialType = searchParams.get("type") === "manual" ? "manual" : "auto";

  const [name, setName] = useState("");
  const [pipelineType, setPipelineType] = useState<"auto" | "manual">(initialType);
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
        body: JSON.stringify({
          name: name.trim(),
          pipeline_type: pipelineType,
          auto_publish: pipelineType !== "manual",
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.message || data.error || "Tạo thất bại.");
      router.push(`/audio/${encodeURIComponent(data.id)}${pipelineType === "manual" ? "?tab=manual" : ""}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Tạo thất bại.");
    } finally {
      setSaving(false);
    }
  }

  const backUrl = pipelineType === "manual" ? "/audio?tab=manual" : "/audio";

  return (
    <div className="mx-auto max-w-xl space-y-4 p-4">
      <div className="flex items-center gap-2">
        <Link href={backUrl} className="text-xs font-bold text-slate-500 hover:text-slate-800">
          ← Audio
        </Link>
        <span className="text-xs text-slate-300">/</span>
        <h1 className="text-lg font-extrabold text-slate-900">
          Tạo Audio Pipeline {pipelineType === "manual" ? "(Thủ Công)" : "(Tự Động)"}
        </h1>
      </div>

      <div className="rounded-2xl bg-white p-4 shadow-sm">
        <div className="mb-4">
          <label className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
            Loại pipeline
          </label>
          <div className="mt-2 inline-flex rounded-xl bg-slate-100 p-1">
            <button
              type="button"
              onClick={() => setPipelineType("auto")}
              className={`rounded-lg px-4 py-1.5 text-xs font-bold transition-colors ${
                pipelineType === "auto"
                  ? "bg-white text-slate-900 shadow-sm"
                  : "text-slate-600 hover:text-slate-900"
              }`}
            >
              Tự Động
            </button>
            <button
              type="button"
              onClick={() => setPipelineType("manual")}
              className={`rounded-lg px-4 py-1.5 text-xs font-bold transition-colors ${
                pipelineType === "manual"
                  ? "bg-white text-slate-900 shadow-sm"
                  : "text-slate-600 hover:text-slate-900"
              }`}
            >
              Thủ Công
            </button>
          </div>
          <p className="mt-1.5 text-xs text-slate-500">
            {pipelineType === "manual"
              ? "Pipeline thủ công: Không tự động scan Facebook, không tự tạo lịch đăng. Dành riêng cho đăng thủ công."
              : "Pipeline tự động: Tự động scan bài đăng và lên lịch đăng định kỳ theo cấu hình."}
          </p>
        </div>

        <label className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
          Tên pipeline
        </label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={pipelineType === "manual" ? "VD: Audio Thủ Công 1" : "VD: Audio Ngôn Tình"}
          className="mt-2 block min-h-[44px] w-full rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none focus:border-indigo-500"
        />
        {error ? (
          <p className="mt-2 text-xs font-semibold text-rose-600">{error}</p>
        ) : null}
        <div className="mt-4 flex gap-2">
          <button
            type="button"
            onClick={() => void handleCreate()}
            disabled={saving || !name.trim()}
            className="inline-flex min-h-[44px] items-center rounded-2xl bg-indigo-600 px-5 py-2 text-sm font-bold text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            {saving ? "Đang tạo…" : "Tạo pipeline"}
          </button>
          <Link
            href={backUrl}
            className="inline-flex min-h-[44px] items-center rounded-2xl border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-50"
          >
            Hủy
          </Link>
        </div>
      </div>
    </div>
  );
}

export default function NewAudioPipelinePage() {
  return (
    <Shell>
      <Suspense fallback={<div className="p-4 text-sm text-slate-500">Đang tải…</div>}>
        <NewAudioPipelineForm />
      </Suspense>
    </Shell>
  );
}
