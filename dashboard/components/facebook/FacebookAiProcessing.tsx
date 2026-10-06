"use client";

import { useEffect, useMemo, useState } from "react";
import { Badge, Card, CardHeader, btnPrimary, btnSecondary, btnSmall } from "@/components/ui";
import { IconCheck, IconRefresh, IconSettings, IconSparkles, IconX } from "@/components/icons";
import type {
  AiModelOption,
  FacebookAiMetadataDto,
  FacebookAiSettingsDto,
  FacebookAiStatsDto,
} from "@/lib/facebook-api";

interface FacebookAiProcessingProps {
  pipelineId: string;
  stats: FacebookAiStatsDto;
  sample: FacebookAiMetadataDto | null;
  initialSettings: FacebookAiSettingsDto | null;
}

const DEFAULTS = {
  enabled: true,
  system_prompt: "",
  title_template: "{title}",
  description_template: "{description}\n\n{hashtags}",
  locked_hashtags: [] as string[],
  language: "vi",
};

const LANGUAGES = [
  { value: "vi", label: "Tiếng Việt" },
  { value: "en", label: "English" },
  { value: "zh", label: "中文" },
  { value: "ja", label: "日本語" },
];

const fieldLabel = "block text-[11px] font-bold uppercase tracking-wider text-slate-500";
const fieldInput =
  "mt-1.5 block w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500";
const hint = "mt-1 text-[11px] text-slate-400";

function shortModel(id: string): string {
  const parts = id.split("/");
  return parts[parts.length - 1] || id;
}

export function FacebookAiProcessing({
  pipelineId,
  stats,
  sample,
  initialSettings,
}: FacebookAiProcessingProps) {
  const [enabled, setEnabled] = useState<boolean>(initialSettings?.enabled ?? DEFAULTS.enabled);
  const [systemPrompt, setSystemPrompt] = useState<string>(
    initialSettings?.system_prompt ?? DEFAULTS.system_prompt,
  );
  const [titleTemplate, setTitleTemplate] = useState<string>(
    initialSettings?.title_template ?? DEFAULTS.title_template,
  );
  const [descriptionTemplate, setDescriptionTemplate] = useState<string>(
    initialSettings?.description_template ?? DEFAULTS.description_template,
  );
  const [lockedHashtags, setLockedHashtags] = useState<string[]>(
    initialSettings?.locked_hashtags ?? DEFAULTS.locked_hashtags,
  );
  const [language, setLanguage] = useState<string>(
    initialSettings?.language ?? DEFAULTS.language,
  );
  const [model, setModel] = useState<string>(initialSettings?.model ?? "");
  const [savedModel, setSavedModel] = useState<string | null>(initialSettings?.model ?? null);
  const [models, setModels] = useState<AiModelOption[] | null>(null);

  const [tagInput, setTagInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const defaultModelId = models?.find((m) => m.is_default)?.id ?? models?.[0]?.id ?? "";
  const effectiveModel = model || initialSettings?.model || defaultModelId;
  const baselineModel = savedModel ?? initialSettings?.model ?? defaultModelId;
  const modelChanged = !!effectiveModel && !!baselineModel && effectiveModel !== baselineModel;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/facebook/ai-models", { cache: "no-store" });
        if (!res.ok) return;
        const data = (await res.json()) as { models?: AiModelOption[] };
        if (!cancelled && Array.isArray(data.models) && data.models.length > 0) {
          setModels(data.models);
        }
      } catch {
        // Fallback to the stored/default model below.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!model && defaultModelId) setModel(defaultModelId);
  }, [defaultModelId, model]);

  const handleAddTag = () => {
    let raw = tagInput.trim();
    if (!raw) return;
    if (!raw.startsWith("#")) raw = `#${raw.replace(/^#+/, "")}`;
    const cleanTag = `#${raw.slice(1).replace(/\s+/g, "")}`;
    if (cleanTag === "#") return;
    if (!lockedHashtags.some((t) => t.toLowerCase() === cleanTag.toLowerCase())) {
      setLockedHashtags([...lockedHashtags, cleanTag]);
    }
    setTagInput("");
  };

  const handleRemoveTag = (tagToRemove: string) => {
    setLockedHashtags(lockedHashtags.filter((t) => t !== tagToRemove));
  };

  const handleResetDefault = () => {
    setEnabled(DEFAULTS.enabled);
    setSystemPrompt(DEFAULTS.system_prompt);
    setTitleTemplate(DEFAULTS.title_template);
    setDescriptionTemplate(DEFAULTS.description_template);
    setLockedHashtags([...DEFAULTS.locked_hashtags]);
    setLanguage(DEFAULTS.language);
    if (defaultModelId) setModel(defaultModelId);
    setSaveError(null);
  };

  const handleSave = async () => {
    if (!titleTemplate.includes("{title}")) {
      setSaveError("Tiêu đề mẫu bắt buộc phải chứa {title}.");
      return;
    }
    if (!effectiveModel) {
      setSaveError("Chưa chọn AI model.");
      return;
    }
    setSaving(true);
    setSaveError(null);
    setSaveSuccess(false);
    try {
      const res = await fetch(`/api/facebook/pipelines/${encodeURIComponent(pipelineId)}/ai-settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled,
          system_prompt: systemPrompt,
          title_template: titleTemplate,
          description_template: descriptionTemplate,
          locked_hashtags: lockedHashtags,
          language,
          model: effectiveModel,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.message ?? data.error ?? `Lỗi HTTP ${res.status}`);
      }
      setModel(data.model ?? effectiveModel);
      setSavedModel(data.model ?? effectiveModel);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 4000);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Không lưu được cài đặt AI.");
    } finally {
      setSaving(false);
    }
  };

  const sampleData = useMemo(() => {
    if (sample) {
      return {
        title: sample.metadata.title || "Tiêu đề video thực tế từ Facebook Reel",
        description:
          sample.metadata.description || "Đoạn mô tả tự nhiên tóm tắt nội dung video từ Reel gốc.",
        hashtags: sample.metadata.hashtags.length > 0 ? sample.metadata.hashtags : ["#shorts", "#reels"],
        sourceUrl: "https://facebook.com/reel/1422636890013099",
        isReal: true,
      };
    }
    return {
      title: "Khám phá bí ẩn đảo hoang và những câu chuyện chưa từng kể",
      description: "Một chuyến hành trình khám phá thiên nhiên hoang dã đầy bất ngờ và lôi cuốn.",
      hashtags: ["#khampha", "#thiennhien", "#shorts"],
      sourceUrl: "https://facebook.com/reel/demo123456",
      isReal: false,
    };
  }, [sample]);

  const preview = useMemo(() => {
    const seen = new Set<string>();
    const mergedTags: string[] = [];
    for (const tag of [...sampleData.hashtags, ...lockedHashtags]) {
      const lower = tag.toLowerCase();
      if (!seen.has(lower)) {
        seen.add(lower);
        mergedTags.push(tag);
      }
    }
    const tplTitle = titleTemplate.trim() || "{title}";
    const finalTitle = (tplTitle.includes("{title}") ? tplTitle.replace("{title}", sampleData.title) : sampleData.title)
      .trim()
      .slice(0, 100);
    const tplDesc = descriptionTemplate || "{description}\n\n{hashtags}";
    const finalDesc = tplDesc
      .replace("{description}", sampleData.description)
      .replace("{hashtags}", mergedTags.join(" "))
      .replace("{source_url}", sampleData.sourceUrl)
      .trim()
      .slice(0, 5000);
    return { finalTitle, finalDesc, mergedTags };
  }, [sampleData, titleTemplate, descriptionTemplate, lockedHashtags]);

  const modelOptions: AiModelOption[] =
    models ??
    (effectiveModel
      ? [{ id: effectiveModel, label: effectiveModel, is_default: true }]
      : []);

  return (
    <div className="space-y-4">
      {/* Stats */}
      <Card>
        <CardHeader
          title="AI Processing"
          subtitle="ToolNet AI viết metadata YouTube"
          icon={<IconSparkles size={16} />}
        />
        <div className="flex items-center gap-2 px-4 pt-1 sm:px-5">
          {[
            { l: "Generated", v: stats.generated, cls: "bg-emerald-50 text-emerald-700 ring-emerald-100" },
            { l: "Pending", v: stats.pending, cls: "bg-amber-50 text-amber-700 ring-amber-100" },
            { l: "Failed", v: stats.failed, cls: "bg-rose-50 text-rose-700 ring-rose-100" },
          ].map((s) => (
            <div
              key={s.l}
              className={`flex-1 rounded-2xl px-3 py-2.5 text-center ring-1 ring-inset ${s.cls}`}
            >
              <div className="tnum text-xl font-black leading-none">{s.v}</div>
              <div className="mt-1 text-[10px] font-bold uppercase tracking-wider opacity-80">{s.l}</div>
            </div>
          ))}
        </div>
        <div className="px-4 pb-4 pt-3 sm:px-5">
          {sample ? (
            <div className="rounded-2xl bg-slate-50 p-3 ring-1 ring-inset ring-slate-100">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
                  Mẫu thực tế
                </span>
                <Badge tone="indigo">{sample.model ?? "ToolNet AI"}</Badge>
              </div>
              <p className="mt-1.5 break-words text-sm font-bold text-slate-900">{sample.metadata.title}</p>
              {sample.metadata.description ? (
                <p className="mt-1 line-clamp-2 break-words text-xs text-slate-600">{sample.metadata.description}</p>
              ) : null}
              {sample.metadata.hashtags.length > 0 ? (
                <p className="mt-1.5 break-words text-xs font-semibold text-indigo-600">
                  {sample.metadata.hashtags.join(" ")}
                </p>
              ) : null}
            </div>
          ) : stats.generated > 0 ? (
            <p className="rounded-2xl bg-indigo-50/70 p-3 text-xs text-indigo-900 ring-1 ring-inset ring-indigo-100">
              Đã có <strong>{stats.generated}</strong> reel được tạo metadata AI.
            </p>
          ) : (
            <p className="text-xs text-slate-500">
              Chưa có metadata nào. Bật AI và chạy scan/worker để ToolNet bắt đầu viết.
            </p>
          )}
        </div>
      </Card>

      {/* Model */}
      <Card>
        <CardHeader
          title="AI Model"
          subtitle="Model viết metadata cho pipeline này"
          icon={<IconSparkles size={16} />}
        />
        <div className="space-y-2 px-4 pb-4 sm:px-5">
          {modelOptions.length === 0 ? (
            <p className="text-xs text-slate-500">Đang tải danh sách model…</p>
          ) : (
            modelOptions.map((m) => {
              const active = m.id === effectiveModel;
              return (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => setModel(m.id)}
                  className={`flex min-h-[44px] w-full items-center gap-3 rounded-2xl border bg-white px-4 py-2.5 text-left shadow-sm transition ${
                    active
                      ? "border-indigo-400 ring-2 ring-indigo-100"
                      : "border-slate-200 hover:border-indigo-200 hover:bg-indigo-50/40"
                  }`}
                >
                  <span
                    className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-xl text-sm font-black ${
                      active ? "bg-indigo-600 text-white" : "bg-slate-100 text-slate-500"
                    }`}
                  >
                    ✦
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-mono text-xs font-bold text-slate-900">
                      {shortModel(m.id)}
                    </span>
                    <span className="block truncate text-[11px] text-slate-400">{m.id}</span>
                  </span>
                  {m.is_default ? (
                    <Badge tone="slate">Mặc định</Badge>
                  ) : null}
                  {active ? <IconCheck size={16} className="shrink-0 text-indigo-600" /> : null}
                </button>
              );
            })
          )}
          {modelChanged ? (
            <p className="rounded-xl bg-amber-50 p-2.5 text-[11px] font-semibold text-amber-800 ring-1 ring-inset ring-amber-100">
              Đổi model sẽ khiến toàn bộ metadata regenerate lại theo model mới. Nhấn Lưu để áp dụng.
            </p>
          ) : null}
        </div>
      </Card>

      {/* General */}
      <Card>
        <CardHeader title="Chung" subtitle="Bật/tắt AI và ngôn ngữ đầu ra" icon={<IconSettings size={16} />} />
        <div className="space-y-3 px-4 pb-4 sm:px-5">
          <button
            type="button"
            role="switch"
            aria-checked={enabled}
            onClick={() => setEnabled(!enabled)}
            className="flex w-full items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white p-3.5 text-left shadow-sm"
          >
            <span className="min-w-0">
              <span className="block text-sm font-extrabold text-slate-900">
                Kích hoạt AI {enabled ? "· ON" : "· OFF"}
              </span>
              <span className="mt-0.5 block text-xs text-slate-500">
                {enabled
                  ? "ToolNet viết lại tiêu đề, mô tả trước khi đăng."
                  : "Tắt: video chưa có AI sẽ không được đăng."}
              </span>
            </span>
            <span className={`relative inline-flex h-6 w-11 shrink-0 rounded-full transition-colors ${enabled ? "bg-indigo-600" : "bg-slate-300"}`}>
              <span className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition ${enabled ? "translate-x-5" : "translate-x-0"} mt-0.5 ${enabled ? "ml-0.5" : "ml-0.5"}`} />
            </span>
          </button>
          <div>
            <label className={fieldLabel}>Ngôn ngữ</label>
            <select value={language} onChange={(e) => setLanguage(e.target.value)} className={fieldInput}>
              {LANGUAGES.map((l) => (
                <option key={l.value} value={l.value}>
                  {l.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </Card>

      {/* Templates */}
      <Card>
        <CardHeader title="Mẫu tiêu đề & mô tả" subtitle="Biến: {title} {description} {hashtags} {source_url}" />
        <div className="space-y-4 px-4 pb-4 sm:px-5">
          <div>
            <label className={fieldLabel}>
              Title template <span className="text-rose-500">*</span>
            </label>
            <input
              type="text"
              value={titleTemplate}
              onChange={(e) => setTitleTemplate(e.target.value)}
              placeholder="{title} | Tên kênh"
              className={fieldInput}
            />
          </div>
          <div>
            <div className="flex flex-wrap items-center justify-between gap-1">
              <label className={fieldLabel}>Description template</label>
              <div className="flex gap-1">
                {["{description}", "{hashtags}", "{source_url}"].map((v) => (
                  <button
                    key={v}
                    type="button"
                    onClick={() => setDescriptionTemplate((prev) => `${prev} ${v}`)}
                    className="rounded-lg bg-slate-100 px-2 py-1 font-mono text-[11px] font-bold text-slate-600 hover:bg-slate-200"
                  >
                    {v}
                  </button>
                ))}
              </div>
            </div>
            <textarea
              rows={3}
              value={descriptionTemplate}
              onChange={(e) => setDescriptionTemplate(e.target.value)}
              className={`${fieldInput} font-mono`}
            />
          </div>
        </div>
      </Card>

      {/* Style + tags */}
      <Card>
        <CardHeader title="Phong cách & hashtag" subtitle="System prompt bổ sung + hashtag cố định" />
        <div className="space-y-4 px-4 pb-4 sm:px-5">
          <div>
            <label className={fieldLabel}>System prompt bổ sung</label>
            <textarea
              rows={2}
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              placeholder="VD: Viết kịch tính, gây tò mò mạnh…"
              className={fieldInput}
            />
          </div>
          <div>
            <label className={fieldLabel}>Hashtag cố định</label>
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5 rounded-xl border border-slate-200 bg-white p-2">
              {lockedHashtags.map((tag) => (
                <span
                  key={tag}
                  className="inline-flex items-center gap-1 rounded-lg bg-indigo-50 px-2 py-1 text-xs font-bold text-indigo-700"
                >
                  {tag}
                  <button
                    type="button"
                    onClick={() => handleRemoveTag(tag)}
                    className="hover:text-rose-600 focus:outline-none"
                    aria-label={`Xóa tag ${tag}`}
                  >
                    <IconX size={13} />
                  </button>
                </span>
              ))}
              <div className="flex min-w-[140px] flex-1 items-center gap-1">
                <input
                  type="text"
                  value={tagInput}
                  onChange={(e) => setTagInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === ",") {
                      e.preventDefault();
                      handleAddTag();
                    }
                  }}
                  placeholder="#shorts…"
                  className="w-full border-none p-1 text-xs text-slate-900 focus:outline-none focus:ring-0"
                />
                <button
                  type="button"
                  onClick={handleAddTag}
                  disabled={!tagInput.trim()}
                  className="shrink-0 rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-bold text-slate-700 hover:bg-slate-200 disabled:opacity-40"
                >
                  Thêm
                </button>
              </div>
            </div>
          </div>
          {saveSuccess ? (
            <div className="flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3.5 py-2.5 text-xs font-bold text-emerald-800">
              <IconCheck size={16} className="shrink-0 text-emerald-600" />
              <span>Đã lưu cài đặt AI.</span>
            </div>
          ) : null}
          {saveError ? (
            <div className="rounded-xl border border-rose-200 bg-rose-50 px-3.5 py-2.5 text-xs font-bold text-rose-800">
              {saveError}
            </div>
          ) : null}
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={saving}
              onClick={handleSave}
              className={`${btnPrimary} min-h-[44px]`}
            >
              {saving ? "Đang lưu…" : "Lưu cài đặt"}
            </button>
            <button
              type="button"
              disabled={saving}
              onClick={handleResetDefault}
              className={`${btnSecondary} inline-flex min-h-[44px] items-center gap-1.5`}
            >
              <IconRefresh size={14} />
              Mặc định
            </button>
          </div>
        </div>
      </Card>

      {/* Preview */}
      <Card>
        <CardHeader
          title="Xem trước"
          subtitle={sampleData.isReal ? "Từ video thực tế trong pipeline" : "Dữ liệu mô phỏng"}
          icon={<IconSparkles size={16} />}
        />
        <div className="space-y-3 px-4 pb-4 sm:px-5">
          <div className="rounded-2xl bg-slate-50 p-3 ring-1 ring-inset ring-slate-100">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Title</span>
              <span className={`text-[11px] font-bold ${preview.finalTitle.length > 90 ? "text-amber-600" : "text-slate-400"}`}>
                {preview.finalTitle.length}/100
              </span>
            </div>
            <p className="mt-1 break-words text-sm font-extrabold text-slate-900">{preview.finalTitle}</p>
          </div>
          <div className="rounded-2xl bg-slate-50 p-3 ring-1 ring-inset ring-slate-100">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Description</span>
              <span className="text-[11px] font-bold text-slate-400">{preview.finalDesc.length}/5000</span>
            </div>
            <div className="mt-1.5 max-h-44 overflow-y-auto whitespace-pre-wrap break-words font-sans text-xs text-slate-700">
              {preview.finalDesc}
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {preview.mergedTags.map((tag) => {
              const isLocked = lockedHashtags.some((t) => t.toLowerCase() === tag.toLowerCase());
              return (
                <span
                  key={tag}
                  className={`inline-block break-all rounded-lg px-2 py-0.5 text-xs font-bold ${
                    isLocked ? "bg-indigo-100 text-indigo-800" : "bg-slate-100 text-slate-700"
                  }`}
                >
                  {tag}
                </span>
              );
            })}
          </div>
          {!sampleData.isReal ? (
            <button type="button" onClick={handleSave} disabled={saving} className={`${btnSmall}`}>
              Lưu để áp dụng cho video thật
            </button>
          ) : null}
        </div>
      </Card>
    </div>
  );
}
