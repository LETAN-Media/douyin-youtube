"use client";

import { useMemo, useState } from "react";
import { Badge, Card, CardHeader, btnPrimary, btnSecondary, btnSmall } from "@/components/ui";
import { IconCheck, IconRefresh, IconSettings, IconSparkles, IconX } from "@/components/icons";
import type {
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
  { value: "vi", label: "Tiếng Việt (vi)" },
  { value: "en", label: "English (en)" },
  { value: "zh", label: "Tiếng Trung (zh)" },
  { value: "ja", label: "Tiếng Nhật (ja)" },
];

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

  const [tagInput, setTagInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Add a tag to lockedHashtags
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
    setSaveError(null);
  };

  const handleSave = async () => {
    if (!titleTemplate.includes("{title}")) {
      setSaveError("Tiêu đề mẫu bắt buộc phải chứa {title}.");
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
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.message ?? data.error ?? `Lỗi HTTP ${res.status}`);
      }

      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 4000);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Không lưu được cài đặt AI.");
    } finally {
      setSaving(false);
    }
  };

  // Preview calculations
  const sampleData = useMemo(() => {
    if (sample) {
      return {
        title: sample.metadata.title || "Tiêu đề video thực tế từ Facebook Reel",
        description:
          sample.metadata.description ||
          "Đoạn mô tả tự nhiên tóm tắt nội dung video từ Reel gốc.",
        hashtags: sample.metadata.hashtags.length > 0 ? sample.metadata.hashtags : ["#shorts", "#reels"],
        sourceUrl: "https://facebook.com/reel/1422636890013099",
        isReal: true,
      };
    }
    return {
      title: "Khám phá bí ẩn đảo hoang và những câu chuyện chưa từng kể",
      description:
        "Một chuyến hành trình khám phá thiên nhiên hoang dã đầy bất ngờ và lôi cuốn.",
      hashtags: ["#khampha", "#thiennhien", "#shorts"],
      sourceUrl: "https://facebook.com/reel/demo123456",
      isReal: false,
    };
  }, [sample]);

  const preview = useMemo(() => {
    const rawTitle = sampleData.title;
    const rawDesc = sampleData.description;

    // Merge hashtags: AI sample hashtags + locked hashtags (deduped)
    const seen = new Set<string>();
    const mergedTags: string[] = [];

    for (const tag of sampleData.hashtags) {
      const lower = tag.toLowerCase();
      if (!seen.has(lower)) {
        seen.add(lower);
        mergedTags.push(tag);
      }
    }
    for (const tag of lockedHashtags) {
      const lower = tag.toLowerCase();
      if (!seen.has(lower)) {
        seen.add(lower);
        mergedTags.push(tag);
      }
    }

    const tplTitle = titleTemplate.trim() || "{title}";
    const finalTitle = (tplTitle.includes("{title}") ? tplTitle.replace("{title}", rawTitle) : rawTitle)
      .trim()
      .slice(0, 100);

    const tplDesc = descriptionTemplate || "{description}\n\n{hashtags}";
    const tagsString = mergedTags.join(" ");
    const finalDesc = tplDesc
      .replace("{description}", rawDesc)
      .replace("{hashtags}", tagsString)
      .replace("{source_url}", sampleData.sourceUrl)
      .trim()
      .slice(0, 5000);

    return {
      rawTitle,
      rawDesc,
      mergedTags,
      finalTitle,
      finalDesc,
    };
  }, [sampleData, titleTemplate, descriptionTemplate, lockedHashtags]);

  return (
    <div className="space-y-6">
      {/* PHẦN 1: AI STATISTICS */}
      <Card>
        <CardHeader
          title="AI Statistics"
          subtitle="Tình trạng xử lý metadata YouTube qua ToolNet AI"
          icon={<IconSparkles size={16} />}
        />
        <div className="grid gap-4 p-4 sm:px-5">
          <div className="grid grid-cols-3 gap-2 text-center">
            {[
              { l: "Generated", v: stats.generated, color: "text-emerald-700 bg-emerald-50/70" },
              { l: "Pending", v: stats.pending, color: "text-amber-700 bg-amber-50/70" },
              { l: "Failed", v: stats.failed, color: "text-rose-700 bg-rose-50/70" },
            ].map((s) => (
              <div key={s.l} className={`rounded-xl px-2 py-3 border border-slate-100 ${s.color}`}>
                <dt className="text-[11px] font-bold uppercase tracking-wider text-slate-500">{s.l}</dt>
                <dd className="tnum mt-1 text-2xl font-black">{s.v}</dd>
              </div>
            ))}
          </div>

          {sample ? (
            <div className="rounded-xl border border-slate-200/80 bg-slate-50/50 p-3.5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs font-bold text-slate-700">Mẫu metadata thực tế đã generate</span>
                <Badge tone="indigo">{sample.model ?? "ToolNet AI"}</Badge>
              </div>
              <p className="mt-2 text-sm font-bold text-slate-900 break-words">{sample.metadata.title}</p>
              {sample.metadata.description ? (
                <p className="mt-1 line-clamp-2 text-xs text-slate-600 break-words">{sample.metadata.description}</p>
              ) : null}
              {sample.metadata.hashtags.length > 0 ? (
                <p className="mt-1.5 text-xs font-semibold text-indigo-600 break-words">
                  {sample.metadata.hashtags.join(" ")}
                </p>
              ) : null}
            </div>
          ) : stats.generated > 0 ? (
            <div className="rounded-xl border border-indigo-100 bg-indigo-50/60 p-3 text-xs text-indigo-900">
              Đã có <strong>{stats.generated}</strong> reel được tạo metadata AI trong database.
            </div>
          ) : (
            <p className="text-xs text-slate-500">
              Chưa có metadata nào được generate cho pipeline này. Khi kích hoạt và chạy tự động hoặc thủ công, ToolNet AI sẽ tạo metadata.
            </p>
          )}
        </div>
      </Card>

      {/* PHẦN 2: AI SETTINGS */}
      <Card>
        <CardHeader
          title="Cấu hình AI riêng cho Pipeline"
          subtitle="Tùy biến phong cách viết, template tiêu đề, mô tả và hashtag cố định"
          icon={<IconSettings size={16} />}
        />
        <div className="space-y-5 p-4 sm:px-5">
          {/* Toggle AI Enabled */}
          <div className="flex items-center justify-between rounded-xl border border-slate-200 bg-white p-3.5 shadow-sm">
            <div className="min-w-0 pr-3">
              <p className="text-sm font-extrabold text-slate-900">Kích hoạt AI Processing</p>
              <p className="text-xs text-slate-500">
                {enabled
                  ? "Đang bật: Video sẽ được ToolNet AI viết lại tiêu đề, mô tả trước khi đăng."
                  : "Đang tắt: Dừng xử lý AI cho pipeline này (hệ thống sẽ từ chối tải và upload video nếu chưa có AI)."}
              </p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={enabled}
              onClick={() => setEnabled(!enabled)}
              className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-indigo-600 focus:ring-offset-2 ${
                enabled ? "bg-indigo-600" : "bg-slate-300"
              }`}
            >
              <span
                className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                  enabled ? "translate-x-5" : "translate-x-0"
                }`}
              />
            </button>
          </div>

          {/* Language Selector */}
          <div>
            <label className="block text-xs font-bold uppercase tracking-wider text-slate-700">
              Ngôn ngữ đầu ra (Language)
            </label>
            <select
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              className="mt-1.5 block w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            >
              {LANGUAGES.map((l) => (
                <option key={l.value} value={l.value}>
                  {l.label}
                </option>
              ))}
            </select>
          </div>

          {/* Title Template */}
          <div>
            <div className="flex items-center justify-between">
              <label className="block text-xs font-bold uppercase tracking-wider text-slate-700">
                Title Template <span className="text-rose-500">*</span>
              </label>
              <span className="text-[11px] font-semibold text-slate-400">
                Placeholder bắt buộc: <code className="text-indigo-600 font-bold">&#123;title&#125;</code>
              </span>
            </div>
            <input
              type="text"
              value={titleTemplate}
              onChange={(e) => setTitleTemplate(e.target.value)}
              placeholder="{title} | Shy Khám Phá"
              className="mt-1.5 block w-full rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
            <p className="mt-1 text-[11px] text-slate-500">
              Ví dụ: <code className="text-slate-700">&#123;title&#125; | Shy Khám Phá</code> (Tối đa 100 ký tự YouTube)
            </p>
          </div>

          {/* Description Template */}
          <div>
            <div className="flex flex-wrap items-center justify-between gap-1">
              <label className="block text-xs font-bold uppercase tracking-wider text-slate-700">
                Description Template
              </label>
              <div className="flex flex-wrap gap-1 text-[11px]">
                <button
                  type="button"
                  onClick={() => setDescriptionTemplate((prev) => `${prev} {description}`)}
                  className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-slate-700 hover:bg-slate-200"
                >
                  &#123;description&#125;
                </button>
                <button
                  type="button"
                  onClick={() => setDescriptionTemplate((prev) => `${prev} {hashtags}`)}
                  className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-slate-700 hover:bg-slate-200"
                >
                  &#123;hashtags&#125;
                </button>
                <button
                  type="button"
                  onClick={() => setDescriptionTemplate((prev) => `${prev} {source_url}`)}
                  className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-slate-700 hover:bg-slate-200"
                >
                  &#123;source_url&#125;
                </button>
              </div>
            </div>
            <textarea
              rows={4}
              value={descriptionTemplate}
              onChange={(e) => setDescriptionTemplate(e.target.value)}
              placeholder="{description}&#10;&#10;Nguồn: {source_url}&#10;&#10;{hashtags}"
              className="mt-1.5 block w-full rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-900 font-mono shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
            <p className="mt-1 text-[11px] text-slate-500">
              Hỗ trợ các biến: <code className="text-slate-700">&#123;description&#125;</code>,{" "}
              <code className="text-slate-700">&#123;hashtags&#125;</code>,{" "}
              <code className="text-slate-700">&#123;source_url&#125;</code>
            </p>
          </div>

          {/* Custom System Prompt */}
          <div>
            <label className="block text-xs font-bold uppercase tracking-wider text-slate-700">
              Custom System Prompt (Bổ sung cho Kênh)
            </label>
            <textarea
              rows={3}
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              placeholder="Ví dụ: Viết theo phong cách kịch tính, hấp dẫn, tạo sự tò mò mạnh mẽ..."
              className="mt-1.5 block w-full rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
            <p className="mt-1 text-[11px] text-slate-500">
              Prompt này sẽ được nối thêm vào Base System Prompt của hệ thống. Hệ thống luôn đảm bảo cấu trúc JSON an toàn tuyệt đối.
            </p>
          </div>

          {/* Locked Hashtags */}
          <div>
            <label className="block text-xs font-bold uppercase tracking-wider text-slate-700">
              Locked Hashtags (Hashtag cố định)
            </label>
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
              <div className="flex flex-1 items-center gap-1 min-w-[140px]">
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
                  placeholder="Thêm hashtag (#shorts, #shykhampha)..."
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
            <p className="mt-1 text-[11px] text-slate-500">
              Các hashtag này luôn được tự động append vào cuối danh sách hashtag AI và tự động loại bỏ trùng lặp.
            </p>
          </div>

          {/* Feedback messages */}
          {saveSuccess ? (
            <div className="flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3.5 py-2.5 text-xs font-bold text-emerald-800">
              <IconCheck size={16} className="text-emerald-600 shrink-0" />
              <span>Đã lưu cài đặt AI vào cơ sở dữ liệu Turso thành công!</span>
            </div>
          ) : null}

          {saveError ? (
            <div className="rounded-xl border border-rose-200 bg-rose-50 px-3.5 py-2.5 text-xs font-bold text-rose-800">
              {saveError}
            </div>
          ) : null}

          {/* Action Buttons */}
          <div className="flex flex-wrap items-center gap-3 pt-2">
            <button
              type="button"
              disabled={saving}
              onClick={handleSave}
              className={`${btnPrimary} min-h-[44px] sm:min-h-[38px]`}
            >
              {saving ? "Đang lưu…" : "Lưu cài đặt"}
            </button>
            <button
              type="button"
              disabled={saving}
              onClick={handleResetDefault}
              className={`${btnSecondary} min-h-[44px] sm:min-h-[38px] inline-flex items-center gap-1.5`}
            >
              <IconRefresh size={14} />
              Khôi phục mặc định
            </button>
          </div>
        </div>
      </Card>

      {/* PHẦN 3: PREVIEW */}
      <Card>
        <CardHeader
          title="Xem trước kết quả (Template Preview)"
          subtitle={
            sampleData.isReal
              ? "Dựa trên video Reel thực tế đã được AI tạo trong pipeline"
              : "Dựa trên dữ liệu mô phỏng (sẽ cập nhật tự động khi có video đầu tiên)"
          }
          icon={<IconSparkles size={16} />}
        />
        <div className="space-y-4 p-4 sm:px-5">
          {/* Title preview */}
          <div className="rounded-xl border border-slate-200 bg-white p-3.5 shadow-sm">
            <div className="flex items-center justify-between text-xs text-slate-500">
              <span className="font-bold uppercase tracking-wider text-slate-400">Tiêu đề gốc từ AI</span>
            </div>
            <p className="mt-1 text-xs text-slate-600 break-words">{preview.rawTitle}</p>

            <div className="mt-3 pt-2 border-t border-slate-100 flex items-center justify-between text-xs">
              <span className="font-extrabold uppercase tracking-wider text-indigo-700">
                Final Title after template
              </span>
              <span
                className={`text-[11px] font-bold ${
                  preview.finalTitle.length > 90 ? "text-amber-600" : "text-slate-400"
                }`}
              >
                {preview.finalTitle.length}/100 ký tự
              </span>
            </div>
            <p className="mt-1 text-sm font-extrabold text-slate-900 break-words">{preview.finalTitle}</p>
          </div>

          {/* Description preview */}
          <div className="rounded-xl border border-slate-200 bg-white p-3.5 shadow-sm">
            <div className="flex items-center justify-between text-xs">
              <span className="font-extrabold uppercase tracking-wider text-indigo-700">
                Final Description after template
              </span>
              <span className="text-[11px] font-bold text-slate-400">
                {preview.finalDesc.length}/5000 ký tự
              </span>
            </div>
            <div className="mt-2 max-h-52 overflow-y-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-2.5 font-sans text-xs text-slate-700 break-words">
              {preview.finalDesc}
            </div>
          </div>

          {/* Hashtags preview */}
          <div className="rounded-xl border border-slate-200 bg-white p-3.5 shadow-sm">
            <div className="flex items-center justify-between text-xs">
              <span className="font-extrabold uppercase tracking-wider text-indigo-700">
                Final Hashtags ({preview.mergedTags.length})
              </span>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {preview.mergedTags.map((tag) => {
                const isLocked = lockedHashtags.some((t) => t.toLowerCase() === tag.toLowerCase());
                return (
                  <span
                    key={tag}
                    className={`inline-block rounded-lg px-2 py-0.5 text-xs font-bold break-all ${
                      isLocked ? "bg-indigo-100 text-indigo-800" : "bg-slate-100 text-slate-700"
                    }`}
                  >
                    {tag}
                    {isLocked ? " (locked)" : ""}
                  </span>
                );
              })}
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
}
