"use client";

import { useEffect, useMemo, useState } from "react";
import { Card, CardHeader, btnSmall } from "@/components/ui";
import type {
  DramaProcessingSettingsDto,
  DramaSeriesJobDto,
  DramaTemplateDto,
} from "@/lib/drama-api";

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
  const [templateEnabled, setTemplateEnabled] = useState(initial.template_enabled ?? false);
  const [templateId, setTemplateId] = useState(initial.template_id ?? "");
  const [templates, setTemplates] = useState<DramaTemplateDto[] | null>(null);
  const [newTplName, setNewTplName] = useState("");
  const [newTplUrl, setNewTplUrl] = useState("");
  const [tplSaving, setTplSaving] = useState(false);
  const [destId, setDestId] = useState(initial.youtube_destination_id ?? "");
  const [autoPublish, setAutoPublish] = useState(initial.auto_publish ?? true);
  const [jobs, setJobs] = useState<DramaSeriesJobDto[] | null>(null);
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

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [tplRes, jobsRes] = await Promise.all([
          fetch("/api/drama/templates", { cache: "no-store" }),
          fetch(`/api/drama/pipelines/${encodeURIComponent(pipelineId)}/jobs`, {
            cache: "no-store",
          }),
        ]);
        if (!cancelled && tplRes.ok) {
          const data = await tplRes.json();
          if (Array.isArray(data.items)) setTemplates(data.items);
        }
        if (!cancelled && jobsRes.ok) {
          const data = await jobsRes.json();
          if (Array.isArray(data.items)) setJobs(data.items);
        }
      } catch {
        // non-fatal; sections stay hidden/empty
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pipelineId]);

  async function handleCreateTemplate() {
    if (tplSaving || !newTplName.trim() || !newTplUrl.trim()) return;
    setTplSaving(true);
    setError(null);
    try {
      const res = await fetch("/api/drama/templates", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newTplName.trim(), asset_url: newTplUrl.trim() }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(
          (typeof data?.message === "string" && data.message) ||
            (typeof data?.error === "string" && data.error) ||
            `HTTP ${res.status}`,
        );
      }
      setTemplates((prev) => [...(prev ?? []), data as DramaTemplateDto]);
      setTemplateId((data as DramaTemplateDto).id);
      setTemplateEnabled(true);
      setNewTplName("");
      setNewTplUrl("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không tạo được template.");
    } finally {
      setTplSaving(false);
    }
  }

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
            template_enabled: templateEnabled,
            template_id: templateEnabled ? templateId || null : null,
            youtube_destination_id: destId.trim() || null,
            auto_publish: autoPublish,
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

        <div className="space-y-3 rounded-2xl border border-slate-200/90 bg-white p-4">
          <label className="flex cursor-pointer items-center justify-between gap-3">
            <span>
              <span className="block text-xs font-extrabold uppercase tracking-wider text-slate-500">
                Template khung hình
              </span>
              <span className="mt-0.5 block text-xs text-slate-500">
                Áp dụng 1 lần duy nhất lên video đã gộp
              </span>
            </span>
            <input
              type="checkbox"
              checked={templateEnabled}
              onChange={(e) => setTemplateEnabled(e.target.checked)}
              className="h-5 w-5 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
            />
          </label>
          {templateEnabled ? (
            <div className="space-y-2">
              <select
                value={templateId}
                onChange={(e) => setTemplateId(e.target.value)}
                className="block min-h-[44px] w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-bold text-slate-900 outline-none focus:border-indigo-500"
              >
                <option value="">— Chọn template —</option>
                {(templates ?? []).map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name} ({t.canvas_width}x{t.canvas_height})
                  </option>
                ))}
              </select>
              {(() => {
                const tpl = (templates ?? []).find((t) => t.id === templateId);
                if (!tpl) return null;
                const isHttp = /^https?:\/\//.test(tpl.asset_url);
                return (
                  <div className="rounded-xl border border-slate-200 bg-slate-50 p-2">
                    {isHttp ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={tpl.asset_url}
                        alt={`Preview ${tpl.name}`}
                        className="max-h-40 w-full rounded-lg object-contain"
                        loading="lazy"
                      />
                    ) : (
                      <p className="p-2 text-xs text-slate-500">
                        Asset: <span className="font-mono">{tpl.asset_url}</span>
                      </p>
                    )}
                    <p className="mt-1 px-1 font-mono text-[11px] text-slate-400">
                      canvas {tpl.canvas_width}x{tpl.canvas_height} · content (
                      {tpl.content_x},{tpl.content_y},{tpl.content_width}x{tpl.content_height})
                    </p>
                  </div>
                );
              })()}
              <div className="flex flex-col gap-2 sm:flex-row">
                <input
                  value={newTplName}
                  onChange={(e) => setNewTplName(e.target.value)}
                  placeholder="Tên template mới"
                  className="min-h-[44px] flex-1 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-bold text-slate-900 outline-none focus:border-indigo-500"
                />
                <input
                  value={newTplUrl}
                  onChange={(e) => setNewTplUrl(e.target.value)}
                  placeholder="https://…/frame.png"
                  inputMode="url"
                  className="min-h-[44px] flex-1 rounded-xl border border-slate-200 bg-white px-3 py-2 font-mono text-xs text-slate-900 outline-none focus:border-indigo-500"
                />
                <button
                  type="button"
                  onClick={() => void handleCreateTemplate()}
                  disabled={tplSaving || !newTplName.trim() || !newTplUrl.trim()}
                  className={`${btnSmall} min-h-[44px] shrink-0 disabled:opacity-60`}
                >
                  {tplSaving ? "Đang tạo…" : "+ Thêm"}
                </button>
              </div>
            </div>
          ) : null}
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="rounded-2xl border border-slate-200/90 bg-white p-4">
            <label className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
              Kênh YouTube (destination ID)
            </label>
            <input
              value={destId}
              onChange={(e) => setDestId(e.target.value)}
              placeholder="ytd_…"
              className="mt-2 block min-h-[44px] w-full rounded-xl border border-slate-200 bg-white px-3 py-2 font-mono text-xs text-slate-900 outline-none focus:border-indigo-500"
            />
          </div>
          <div className="rounded-2xl border border-slate-200/90 bg-white p-4">
            <label className="flex cursor-pointer items-center justify-between gap-3">
              <span>
                <span className="block text-xs font-extrabold uppercase tracking-wider text-slate-500">
                  Auto publish
                </span>
                <span className="mt-0.5 block text-xs text-slate-500">
                  {autoPublish ? "Tự đăng khi job xong" : "Chỉ xử lý, đăng tay"}
                </span>
              </span>
              <input
                type="checkbox"
                checked={autoPublish}
                onChange={(e) => setAutoPublish(e.target.checked)}
                className="h-5 w-5 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
              />
            </label>
          </div>
        </div>

        {jobs !== null && jobs.length > 0 ? (
          <div className="rounded-2xl border border-slate-200/90 bg-white p-4">
            <p className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
              Jobs ({jobs.length})
            </p>
            <ul className="mt-2 space-y-2">
              {jobs.slice(0, 10).map((j) => (
                <li
                  key={j.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-slate-50 px-3 py-2"
                >
                  <span className="font-mono text-[11px] text-slate-500">
                    EP {j.episode_start ?? "?"}–{j.episode_end ?? "?"}
                  </span>
                  <span className="text-xs font-bold text-slate-700">
                    {j.status}
                    {j.stage ? ` · ${j.stage}` : ""}
                    {typeof j.upload_progress === "number" ? ` · ${Math.round(j.upload_progress * 100)}%` : ""}
                  </span>
                  {j.youtube_video_id ? (
                    <span className="font-mono text-[11px] text-emerald-600">{j.youtube_video_id}</span>
                  ) : null}
                  {j.last_error_code ? (
                    <span className="text-[11px] font-bold text-rose-600">{j.last_error_code}</span>
                  ) : null}
                </li>
              ))}
            </ul>
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
