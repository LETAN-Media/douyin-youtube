"use client";

import { useEffect, useState } from "react";
import { Card, CardHeader, btnSmall } from "@/components/ui";
import type { DramaAiSettingsDto } from "@/lib/drama-api";

const LANGS = [
  { value: "vi", label: "VN — Tiếng Việt" },
  { value: "en", label: "EN — English" },
  { value: "zh", label: "ZH — 中文" },
];

interface PreviewResult {
  title: string;
  description: string;
  hashtags: string[];
  language: string;
  model: string;
  cached: boolean;
}

export function DramaAiMetadata({ pipelineId }: { pipelineId: string }) {
  const [settings, setSettings] = useState<DramaAiSettingsDto | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [language, setLanguage] = useState("vi");
  const [genTitle, setGenTitle] = useState(true);
  const [genDesc, setGenDesc] = useState(true);
  const [genTags, setGenTags] = useState(true);
  const [systemPrompt, setSystemPrompt] = useState("");
  const [titleTemplate, setTitleTemplate] = useState("");
  const [descTemplate, setDescTemplate] = useState("");
  const [lockedTags, setLockedTags] = useState("");
  const [series, setSeries] = useState<{ id: string; title: string | null }[]>([]);
  const [previewSeriesId, setPreviewSeriesId] = useState("");
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [saving, setSaving] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);

  function applySettings(data: DramaAiSettingsDto) {
    setSettings(data);
    setEnabled(data.enabled);
    setLanguage(data.language || "vi");
    setGenTitle(data.generate_title);
    setGenDesc(data.generate_description);
    setGenTags(data.generate_hashtags);
    setSystemPrompt(data.system_prompt ?? "");
    setTitleTemplate(data.title_template ?? "");
    setDescTemplate(data.description_template ?? "");
    setLockedTags((data.locked_hashtags ?? []).join(", "));
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [setRes, serRes] = await Promise.all([
          fetch(`/api/drama/pipelines/${encodeURIComponent(pipelineId)}/ai-settings`, {
            cache: "no-store",
          }),
          fetch(`/api/drama/pipelines/${encodeURIComponent(pipelineId)}/series`, {
            cache: "no-store",
          }),
        ]);
        if (cancelled) return;
        if (setRes.ok) {
          const data = (await setRes.json()) as DramaAiSettingsDto;
          applySettings(data);
        }
        if (serRes.ok) {
          const data = await serRes.json();
          const items = Array.isArray(data) ? data : (data.items ?? []);
          setSeries(items.map((s: { id: string; title?: string | null }) => ({
            id: s.id,
            title: s.title ?? null,
          })));
          if (items.length > 0) setPreviewSeriesId(items[0].id);
        }
      } catch {
        // section stays in loading/error state
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pipelineId]);

  async function handleSave() {
    if (saving) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const res = await fetch(
        `/api/drama/pipelines/${encodeURIComponent(pipelineId)}/ai-settings`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            enabled,
            language,
            generate_title: genTitle,
            generate_description: genDesc,
            generate_hashtags: genTags,
            system_prompt: systemPrompt.trim() || null,
            title_template: titleTemplate.trim() || null,
            description_template: descTemplate.trim() || null,
            locked_hashtags: lockedTags.trim() || null,
            expected_config_version: settings?.config_version ?? null,
          }),
        },
      );
      const data = await res.json().catch(() => ({}));
      if (res.status === 409) {
        throw new Error(
          "Cài đặt đã bị thay đổi ở nơi khác. Hãy tải lại trang rồi lưu lại.",
        );
      }
      if (!res.ok) {
        throw new Error(
          (typeof data?.message === "string" && data.message) ||
            (typeof data?.error === "string" && data.error) ||
            `HTTP ${res.status}`,
        );
      }
      setSettings(data as DramaAiSettingsDto);
      setSaved(true);
      setTimeout(() => setSaved(false), 4000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không lưu được cài đặt AI.");
    } finally {
      setSaving(false);
    }
  }

  async function handleReset() {
    if (resetting) return;
    if (!window.confirm("Khôi phục cài đặt AI về mặc định (tắt AI)?")) return;
    setResetting(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/drama/pipelines/${encodeURIComponent(pipelineId)}/ai-settings/reset`,
        { method: "POST" },
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(
          (typeof data?.message === "string" && data.message) ||
            (typeof data?.error === "string" && data.error) ||
            `HTTP ${res.status}`,
        );
      }
      applySettings(data as DramaAiSettingsDto);
      setSaved(true);
      setTimeout(() => setSaved(false), 4000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không khôi phục được cài đặt.");
    } finally {
      setResetting(false);
    }
  }

  async function handleCopy(key: string, text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(key);
      setTimeout(() => setCopied(null), 2000);
    } catch {
      setError("Không sao chép được (trình duyệt chặn clipboard).");
    }
  }

  async function handlePreview(force: boolean) {
    if (previewing || !previewSeriesId) return;
    setPreviewing(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/drama/pipelines/${encodeURIComponent(pipelineId)}/ai-metadata/preview`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            series_id: previewSeriesId,
            language,
            force_regenerate: force,
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
      setPreview(data as PreviewResult);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không tạo thử được metadata.");
    } finally {
      setPreviewing(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title="AI Metadata YouTube"
        subtitle="Tự động tạo tiêu đề, mô tả và hashtag bằng ngôn ngữ riêng của từng kênh. Không đổi ngôn ngữ phụ đề/giọng lồng tiếng của video."
        action={
          <span className="rounded-full bg-indigo-100 px-2.5 py-1 text-[11px] font-bold text-indigo-700">
            Đề xuất
          </span>
        }
      />
      {settings === null ? (
        <p className="text-xs text-slate-400">Đang tải cài đặt AI…</p>
      ) : (
        <div className="space-y-4">
          <label className="flex cursor-pointer items-center justify-between gap-3 rounded-2xl border border-slate-200/90 bg-white p-4">
            <span>
              <span className="block text-xs font-extrabold uppercase tracking-wider text-slate-500">
                Bật AI Metadata
              </span>
              <span className="mt-0.5 block text-xs text-slate-500">
                {enabled ? "AI tạo metadata khi publish" : "Dùng tiêu đề/mô tả mặc định"}
              </span>
            </span>
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
              className="h-5 w-5 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
            />
          </label>

          <div>
            <p className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
              Ngôn ngữ đầu ra
            </p>
            <div className="mt-2 grid grid-cols-3 gap-2">
              {LANGS.map((l) => (
                <button
                  key={l.value}
                  type="button"
                  onClick={() => setLanguage(l.value)}
                  className={`min-h-[44px] rounded-xl border px-2 py-2 text-xs font-bold ${
                    language === l.value
                      ? "border-indigo-600 bg-indigo-50 text-indigo-700"
                      : "border-slate-200 bg-white text-slate-600 hover:border-slate-300"
                  }`}
                >
                  {l.label}
                </button>
              ))}
            </div>
          </div>

          <div>
            <p className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
              Nội dung AI tạo
            </p>
            <div className="mt-2 space-y-2">
              {[
                { label: "Tiêu đề", value: genTitle, set: setGenTitle },
                { label: "Mô tả", value: genDesc, set: setGenDesc },
                { label: "Hashtag", value: genTags, set: setGenTags },
              ].map((c) => (
                <label key={c.label} className="flex cursor-pointer items-center gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={c.value}
                    onChange={(e) => c.set(e.target.checked)}
                    className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                  />
                  {c.label}
                </label>
              ))}
            </div>
          </div>

          <div>
            <label className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
              System Prompt riêng (tùy chọn)
            </label>
            <textarea
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              rows={3}
              placeholder="VD: Thêm câu kêu gọi đăng ký ở cuối mô tả…"
              className="mt-2 block w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-indigo-500"
            />
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
                Title Template
              </label>
              <input
                value={titleTemplate}
                onChange={(e) => setTitleTemplate(e.target.value)}
                placeholder="[Hay] {title}"
                className="mt-2 block min-h-[44px] w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-indigo-500"
              />
            </div>
            <div>
              <label className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
                Hashtag cố định
              </label>
              <input
                value={lockedTags}
                onChange={(e) => setLockedTags(e.target.value)}
                placeholder="#PhimNgan, #Drama"
                className="mt-2 block min-h-[44px] w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-indigo-500"
              />
            </div>
          </div>

          <div>
            <label className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
              Description Template
            </label>
            <textarea
              value={descTemplate}
              onChange={(e) => setDescTemplate(e.target.value)}
              rows={2}
              placeholder="{description}&#10;&#10;{hashtags}"
              className="mt-2 block w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-indigo-500"
            />
            <p className="mt-1 text-[11px] text-slate-400">
              Biến hỗ trợ: {"{title}"} {"{description}"} {"{hashtags}"}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => void handleSave()}
              disabled={saving}
              className={`min-h-[44px] rounded-xl bg-indigo-600 px-4 py-2 text-sm font-bold text-white hover:bg-indigo-700 disabled:opacity-50 ${btnSmall}`}
            >
              {saving ? "Đang lưu…" : "Lưu cài đặt AI"}
            </button>
            <button
              type="button"
              onClick={() => void handleReset()}
              disabled={resetting}
              className={`min-h-[44px] rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm font-bold text-slate-600 hover:border-slate-400 disabled:opacity-50 ${btnSmall}`}
            >
              {resetting ? "Đang khôi phục…" : "Khôi phục mặc định"}
            </button>
            {saved ? <span className="text-xs font-bold text-emerald-600">Đã lưu.</span> : null}
          </div>

          <div className="rounded-2xl border border-slate-200/90 bg-slate-50 p-4">
            <p className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
              Tạo thử metadata
            </p>
            {series.length === 0 ? (
              <p className="mt-2 text-xs text-slate-500">
                Pipeline chưa có series nào để tạo thử.
              </p>
            ) : (
              <div className="mt-2 flex flex-col gap-2 sm:flex-row">
                <select
                  value={previewSeriesId}
                  onChange={(e) => setPreviewSeriesId(e.target.value)}
                  className="block min-h-[44px] flex-1 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-indigo-500"
                >
                  {series.map((s) => (
                    <option key={s.id} value={s.id}>
                      {(s.title ?? s.id).slice(0, 60)}
                    </option>
                  ))}
                </select>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => void handlePreview(false)}
                    disabled={previewing || !enabled}
                    title={enabled ? undefined : "Bật AI Metadata trước khi tạo thử"}
                    className={`min-h-[44px] flex-1 rounded-xl bg-slate-900 px-3 py-2 text-xs font-bold text-white hover:bg-slate-700 disabled:opacity-50 sm:flex-none ${btnSmall}`}
                  >
                    {previewing ? "Đang tạo…" : "Tạo thử"}
                  </button>
                  <button
                    type="button"
                    onClick={() => void handlePreview(true)}
                    disabled={previewing || !enabled || preview === null}
                    title="Bỏ cache, gọi AI lại"
                    className={`min-h-[44px] rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs font-bold text-slate-700 hover:border-slate-400 disabled:opacity-50 ${btnSmall}`}
                  >
                    Tạo lại
                  </button>
                </div>
              </div>
            )}
            {preview !== null ? (
              <div className="mt-3 space-y-2 rounded-xl bg-white p-3">
                <p className="text-xs text-slate-400">
                  {preview.language.toUpperCase()} · {preview.model}
                  {preview.cached ? " · từ cache" : " · vừa tạo"}
                </p>
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm font-bold text-slate-900">{preview.title}</p>
                  <button
                    type="button"
                    onClick={() => void handleCopy("title", preview.title)}
                    className={`shrink-0 rounded-lg border border-slate-200 px-2 py-1 text-[11px] font-bold text-slate-600 hover:border-slate-300 ${btnSmall}`}
                  >
                    {copied === "title" ? "Đã chép" : "Chép"}
                  </button>
                </div>
                <div className="flex items-start justify-between gap-2">
                  <p className="whitespace-pre-wrap text-xs text-slate-600">
                    {preview.description}
                  </p>
                  <button
                    type="button"
                    onClick={() => void handleCopy("desc", preview.description)}
                    className={`shrink-0 rounded-lg border border-slate-200 px-2 py-1 text-[11px] font-bold text-slate-600 hover:border-slate-300 ${btnSmall}`}
                  >
                    {copied === "desc" ? "Đã chép" : "Chép"}
                  </button>
                </div>
                <div className="flex items-start justify-between gap-2">
                  <p className="text-xs font-semibold text-indigo-700">
                    {preview.hashtags.join(" ")}
                  </p>
                  <button
                    type="button"
                    onClick={() => void handleCopy("tags", preview.hashtags.join(" "))}
                    className={`shrink-0 rounded-lg border border-slate-200 px-2 py-1 text-[11px] font-bold text-slate-600 hover:border-slate-300 ${btnSmall}`}
                  >
                    {copied === "tags" ? "Đã chép" : "Chép"}
                  </button>
                </div>
              </div>
            ) : null}
          </div>

          {error !== null ? (
            <p className="rounded-xl bg-rose-50 px-3 py-2 text-xs font-semibold text-rose-700">
              {error}
            </p>
          ) : null}
        </div>
      )}
    </Card>
  );
}
