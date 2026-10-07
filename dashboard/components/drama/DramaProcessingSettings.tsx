"use client";

import { useMemo, useState } from "react";
import { Card, CardHeader, btnSmall } from "@/components/ui";
import type { DramaProcessingSettingsDto } from "@/lib/drama-api";

export type ProcessingMode = "direct_merge" | "translate_sub" | "dub_vi";

const MODES: Array<{
  value: ProcessingMode;
  label: string;
  desc: string;
}> = [
  {
    value: "direct_merge",
    label: "Gộp & đăng trực tiếp",
    desc: "Tải tập → gộp → đăng. Không ASR, không dịch, nhanh nhất.",
  },
  {
    value: "translate_sub",
    label: "Dịch phụ đề",
    desc: "ASR → dịch Việt → gộp + phụ đề Việt. Không lồng tiếng.",
  },
  {
    value: "dub_vi",
    label: "Dịch + lồng tiếng Việt",
    desc: "ASR → dịch → TTS → thay audio → phụ đề Việt.",
  },
];

const CHUNK_PRESETS = [5, 10, 20];

export function DramaProcessingSettings({
  pipelineId,
  initial,
  onSaved,
}: {
  pipelineId: string;
  initial: DramaProcessingSettingsDto;
  onSaved?: (s: DramaProcessingSettingsDto) => void;
}) {
  const [mode, setMode] = useState<ProcessingMode>(initial.processing_mode);
  const [mergeAll, setMergeAll] = useState(initial.merge_all_episodes);
  const [epv, setEpv] = useState<string>(
    initial.episodes_per_video ? String(initial.episodes_per_video) : "20",
  );
  const [customEpv, setCustomEpv] = useState("");
  const [useCustom, setUseCustom] = useState(
    initial.episodes_per_video !== null &&
      !CHUNK_PRESETS.includes(initial.episodes_per_video ?? 0),
  );
  const [targetLang, setTargetLang] = useState(initial.target_language ?? "vi");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [live, setLive] = useState(initial);

  const effectiveEpv = useMemo(() => {
    if (mergeAll) return null;
    if (useCustom) {
      const n = parseInt(customEpv, 10);
      return Number.isFinite(n) ? n : null;
    }
    const n = parseInt(epv, 10);
    return Number.isFinite(n) ? n : null;
  }, [mergeAll, useCustom, customEpv, epv]);

  const plannedVideos = useMemo(() => {
    const total = live.total_episodes;
    if (total <= 0) return 0;
    if (mergeAll || !effectiveEpv) return 1;
    return Math.ceil(total / effectiveEpv);
  }, [live.total_episodes, mergeAll, effectiveEpv]);

  const needsTranslation = mode !== "direct_merge";

  async function handleSave() {
    if (saving) return;
    if (!mergeAll && !effectiveEpv) {
      setError("Chọn số tập mỗi video (1–200).");
      return;
    }
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const res = await fetch(
        `/api/drama/pipelines/${encodeURIComponent(pipelineId)}/processing-settings`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            processing_mode: mode,
            merge_all_episodes: mergeAll,
            episodes_per_video: effectiveEpv,
            target_language: needsTranslation ? targetLang.trim().toLowerCase() || null : null,
            subtitle_enabled: mode !== "direct_merge" ? live.subtitle_enabled : true,
            tts_enabled: mode === "dub_vi",
          }),
        },
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(
          (typeof data?.message === "string" && data.message) ||
            (typeof data?.error === "string" && data.error) ||
            `HTTP ${res.status}`,
        );
      }
      setLive(data as DramaProcessingSettingsDto);
      onSaved?.(data as DramaProcessingSettingsDto);
      setSaved(true);
      setTimeout(() => setSaved(false), 4000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không lưu được cài đặt.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title="Chế độ xử lý"
        subtitle="Mỗi pipeline chọn workflow riêng — kênh reupload đi đường ngắn"
      />
      <div className="space-y-4 p-4 sm:px-5">
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          {MODES.map((m) => {
            const active = mode === m.value;
            return (
              <button
                key={m.value}
                type="button"
                onClick={() => setMode(m.value)}
                className={`min-h-[44px] rounded-2xl border bg-white p-3.5 text-left shadow-sm transition ${
                  active
                    ? "border-indigo-400 ring-2 ring-indigo-100"
                    : "border-slate-200 hover:border-indigo-200 hover:bg-indigo-50/40"
                }`}
              >
                <span className="flex items-center gap-2 text-sm font-extrabold text-slate-900">
                  <span
                    className={`flex h-4 w-4 items-center justify-center rounded-full border-2 ${
                      active ? "border-indigo-600" : "border-slate-300"
                    }`}
                  >
                    {active ? <span className="h-2 w-2 rounded-full bg-indigo-600" /> : null}
                  </span>
                  {m.label}
                </span>
                <span className="mt-1 block text-xs leading-relaxed text-slate-500">{m.desc}</span>
              </button>
            );
          })}
        </div>

        <div className="rounded-2xl border border-slate-200/90 bg-white p-4">
          <p className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
            Gộp số tập mỗi video
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setMergeAll(true)}
              className={`inline-flex min-h-[44px] items-center rounded-xl px-4 py-2 text-xs font-bold transition ${
                mergeAll
                  ? "bg-indigo-600 text-white shadow-sm"
                  : "border border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
              }`}
            >
              Toàn bộ
            </button>
            {CHUNK_PRESETS.map((n) => (
              <button
                key={n}
                type="button"
                onClick={() => {
                  setMergeAll(false);
                  setUseCustom(false);
                  setEpv(String(n));
                }}
                className={`inline-flex min-h-[44px] items-center rounded-xl px-4 py-2 text-xs font-bold transition ${
                  !mergeAll && !useCustom && epv === String(n)
                    ? "bg-indigo-600 text-white shadow-sm"
                    : "border border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                }`}
              >
                {n}
              </button>
            ))}
            <button
              type="button"
              onClick={() => {
                setMergeAll(false);
                setUseCustom(true);
              }}
              className={`inline-flex min-h-[44px] items-center rounded-xl px-4 py-2 text-xs font-bold transition ${
                !mergeAll && useCustom
                  ? "bg-indigo-600 text-white shadow-sm"
                  : "border border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
              }`}
            >
              Tuỳ chỉnh
            </button>
            {!mergeAll && useCustom ? (
              <input
                type="number"
                min={1}
                max={200}
                value={customEpv}
                onChange={(e) => setCustomEpv(e.target.value)}
                placeholder="VD: 15"
                className="inline-flex min-h-[44px] w-28 items-center rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-bold text-slate-900 outline-none focus:border-indigo-500"
              />
            ) : null}
          </div>
          <p className="mt-2 text-xs font-semibold text-indigo-700">
            {live.total_episodes > 0 ? (
              <>
                {live.total_episodes} tập
                {!mergeAll && effectiveEpv ? ` / ${effectiveEpv}` : ""} → {plannedVideos}{" "}
                video
              </>
            ) : (
              "Chưa có tập nào trong kho — quét series trước."
            )}
          </p>
        </div>

        {needsTranslation ? (
          <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-slate-200/90 bg-white p-4">
            <label className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
              Ngôn ngữ đích
            </label>
            <input
              value={targetLang}
              onChange={(e) => setTargetLang(e.target.value)}
              maxLength={10}
              placeholder="vi"
              className="inline-flex min-h-[44px] w-28 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-bold text-slate-900 outline-none focus:border-indigo-500"
            />
          </div>
        ) : null}

        {error ? <p className="text-xs font-semibold text-rose-600">{error}</p> : null}
        {saved ? (
          <p className="text-xs font-semibold text-emerald-600">Đã lưu cài đặt xử lý.</p>
        ) : null}
        <button
          type="button"
          onClick={() => void handleSave()}
          disabled={saving}
          className="inline-flex min-h-[44px] items-center rounded-2xl bg-indigo-600 px-5 py-2.5 text-sm font-extrabold text-white shadow-sm transition hover:bg-indigo-500 disabled:cursor-wait disabled:opacity-70"
        >
          {saving ? "Đang lưu…" : "Lưu cài đặt"}
        </button>
      </div>
    </Card>
  );
}
