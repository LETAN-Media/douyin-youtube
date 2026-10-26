"use client";

import { useEffect, useState } from "react";
import { Badge, Card, CardHeader, Spinner, btnPrimary, btnSecondary, btnSmall, inputCls, labelCls } from "@/components/ui";
import { IconCheck, IconRefresh, IconSettings, IconSparkles, IconX } from "@/components/icons";
import type { TikTokAiModelOption, TikTokAiSettingsDto } from "@/lib/tiktok-api";

interface TikTokAiSettingsProps {
  pipelineId: string;
  initialSettings: TikTokAiSettingsDto | null;
}

const DEFAULTS: TikTokAiSettingsDto = {
  pipeline_id: "",
  enabled: true,
  provider: "toolnet",
  model: "groq/openai/gpt-oss-120b",
  system_prompt:
    "Bạn là chuyên gia sáng tạo nội dung YouTube Shorts hàng đầu. Hãy viết tiêu đề, mô tả và hashtag hấp dẫn, tối ưu hóa SEO và giữ chân người xem.",
  title_prompt: "Viết tiêu đề ngắn gọn (dưới 80 ký tự), kích thích sự tò mò, chứa từ khóa chính.",
  description_prompt: "Viết mô tả 2-3 câu ngắn gọn về nội dung video, kèm lời kêu gọi like và subscribe.",
  hashtag_prompt: "Chọn các hashtag thịnh hành, liên quan mật thiết đến chủ đề video.",
  title_template: "{title}",
  description_template: "{description}\n\n{hashtags}",
  locked_hashtags: ["#shorts"],
  language: "vi",
  max_hashtags: 10,
  include_emojis: true,
  tone: "engaging",
  required_keywords: "",
  forbidden_keywords: "",
};

const LANGUAGES = [
  { value: "vi", label: "Tiếng Việt" },
  { value: "en", label: "English" },
  { value: "zh", label: "中文" },
  { value: "ja", label: "日本語" },
];

const TONES = [
  { value: "engaging", label: "Hấp dẫn, sôi động (Khuyên dùng)" },
  { value: "humorous", label: "Hài hước, dí dỏm" },
  { value: "professional", label: "Chuyên nghiệp, tri thức" },
  { value: "dramatic", label: "Kịch tính, tò mò" },
  { value: "storytelling", label: "Kể chuyện, sâu lắng" },
];

export function TikTokAiSettings({ pipelineId, initialSettings }: TikTokAiSettingsProps) {
  const init = initialSettings || DEFAULTS;

  const [enabled, setEnabled] = useState<boolean>(init.enabled ?? true);
  const [provider, setProvider] = useState<string>(init.provider || "toolnet");
  const [model, setModel] = useState<string>(init.model || "groq/openai/gpt-oss-120b");
  const [systemPrompt, setSystemPrompt] = useState<string>(init.system_prompt || DEFAULTS.system_prompt);
  const [titlePrompt, setTitlePrompt] = useState<string>(init.title_prompt || DEFAULTS.title_prompt);
  const [descriptionPrompt, setDescriptionPrompt] = useState<string>(init.description_prompt || DEFAULTS.description_prompt);
  const [hashtagPrompt, setHashtagPrompt] = useState<string>(init.hashtag_prompt || DEFAULTS.hashtag_prompt);
  const [language, setLanguage] = useState<string>(init.language || "vi");
  const [maxHashtags, setMaxHashtags] = useState<number>(init.max_hashtags || 10);
  const [includeEmojis, setIncludeEmojis] = useState<boolean>(init.include_emojis ?? true);
  const [tone, setTone] = useState<string>(init.tone || "engaging");
  const [requiredKeywords, setRequiredKeywords] = useState<string>(init.required_keywords || "");
  const [forbiddenKeywords, setForbiddenKeywords] = useState<string>(init.forbidden_keywords || "");
  const [lockedHashtags, setLockedHashtags] = useState<string[]>(init.locked_hashtags || ["#shorts"]);

  // Tag input
  const [tagInput, setTagInput] = useState("");

  // Models list
  const [models, setModels] = useState<TikTokAiModelOption[]>([
    { id: "groq/openai/gpt-oss-120b", label: "Groq / GPT-OSS 120B (Nhanh & Tối ưu SEO)", provider: "toolnet", is_default: true },
    { id: "openrouter/openai/gpt-4o-mini", label: "GPT-4o Mini (Thông minh & Ổn định)", provider: "toolnet" },
    { id: "openrouter/openai/gpt-4o", label: "GPT-4o (Chất lượng cao nhất)", provider: "toolnet" },
    { id: "openrouter/anthropic/claude-3.5-sonnet", label: "Claude 3.5 Sonnet (Văn phong mượt mà)", provider: "toolnet" },
  ]);

  // Saving states
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Test AI states
  const [showTest, setShowTest] = useState(false);
  const [testCaption, setTestCaption] = useState("Lâu rồi ko gặp các con, vẫn là mom đây #citracaimoc #citrachoighelam_19");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ title: string; description: string; hashtags: string[]; model: string } | null>(null);
  const [testError, setTestError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function loadModels() {
      try {
        const res = await fetch("/api/tiktok/ai/models");
        if (res.ok) {
          const data = await res.json();
          if (!cancelled && Array.isArray(data.models) && data.models.length > 0) {
            setModels(data.models);
          }
        }
      } catch {
        // use defaults
      }
    }
    void loadModels();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleAddTag = () => {
    let raw = tagInput.trim();
    if (!raw) return;
    if (!raw.startsWith("#")) raw = `#${raw}`;
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

  const handleSave = async () => {
    setSaving(true);
    setSaveError(null);
    setSaveSuccess(false);

    try {
      const res = await fetch(`/api/tiktok/pipelines/${encodeURIComponent(pipelineId)}/ai-settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled,
          provider,
          model,
          system_prompt: systemPrompt,
          title_prompt: titlePrompt,
          description_prompt: descriptionPrompt,
          hashtag_prompt: hashtagPrompt,
          language,
          max_hashtags: maxHashtags,
          include_emojis: includeEmojis,
          tone,
          required_keywords: requiredKeywords,
          forbidden_keywords: forbiddenKeywords,
          locked_hashtags: lockedHashtags,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || data.message || "Không thể lưu cấu hình AI.");
      }

      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 4000);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Lỗi lưu cấu hình AI.");
    } finally {
      setSaving(false);
    }
  };

  const handleRunTest = async () => {
    setTesting(true);
    setTestError(null);
    setTestResult(null);

    try {
      const res = await fetch("/api/tiktok/ai/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pipeline_id: pipelineId,
          sample_caption: testCaption,
          settings: {
            enabled,
            provider,
            model,
            system_prompt: systemPrompt,
            title_prompt: titlePrompt,
            description_prompt: descriptionPrompt,
            hashtag_prompt: hashtagPrompt,
            language,
            max_hashtags: maxHashtags,
            include_emojis: includeEmojis,
            tone,
            required_keywords: requiredKeywords,
            forbidden_keywords: forbiddenKeywords,
            locked_hashtags: lockedHashtags,
          },
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || data.message || "Kiểm tra AI thất bại.");
      }
      setTestResult(data);
    } catch (err) {
      setTestError(err instanceof Error ? err.message : "Lỗi khi chạy thử nghiệm AI.");
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Notifications */}
      {saveSuccess && (
        <div className="flex items-center gap-2 rounded-2xl bg-emerald-50 p-4 text-sm font-bold text-emerald-800 border border-emerald-200 shadow-sm">
          <IconCheck size={18} />
          <span>Đã lưu thành công cấu hình AI độc lập cho Pipeline này!</span>
        </div>
      )}
      {saveError && (
        <div className="flex items-center gap-2 rounded-2xl bg-rose-50 p-4 text-sm font-bold text-rose-800 border border-rose-200 shadow-sm">
          <IconX size={18} />
          <span>{saveError}</span>
        </div>
      )}

      {/* Main Settings Card */}
      <Card>
        <CardHeader
          title="Cấu hình AI Metadata cho TikTok Pipeline"
          subtitle="Tự động tạo tiêu đề, mô tả và hashtag SEO YouTube riêng biệt cho pipeline này"
          icon={<IconSparkles size={18} />}
          action={
            <div className="flex items-center gap-2">
              <label className="relative inline-flex cursor-pointer items-center">
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={(e) => setEnabled(e.target.checked)}
                  className="peer sr-only"
                />
                <div className="peer h-6 w-11 rounded-full bg-slate-200 after:absolute after:left-[2px] after:top-[2px] after:h-5 after:w-5 after:rounded-full after:border after:border-slate-300 after:bg-white after:transition-all after:content-[''] peer-checked:bg-indigo-600 peer-checked:after:translate-x-full peer-checked:after:border-white"></div>
                <span className="ml-2 text-xs font-bold text-slate-700">
                  {enabled ? "AI Đang Bật" : "AI Đang Tắt"}
                </span>
              </label>
            </div>
          }
        />

        <div className="space-y-5 p-4 sm:p-6">
          {/* Row 1: Provider & Model */}
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className={labelCls}>Nhà cung cấp AI (Provider)</label>
              <select
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
                className={inputCls}
              >
                <option value="toolnet">ToolNet AI Gateway (Khuyên dùng - Đa mô hình)</option>
              </select>
              <p className="mt-1 text-[11px] text-slate-400">
                API key được bảo mật ở backend qua môi trường máy chủ.
              </p>
            </div>

            <div>
              <label className={labelCls}>Mô hình AI (Model)</label>
              <select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className={inputCls}
              >
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-[11px] text-slate-400">
                Model ID đang dùng: <span className="font-mono text-slate-600">{model}</span>
              </p>
            </div>
          </div>

          {/* Row 2: System Prompt */}
          <div>
            <div className="flex items-center justify-between">
              <label className={labelCls}>System Prompt (Định hướng phong cách AI)</label>
              <button
                type="button"
                onClick={() => setSystemPrompt(DEFAULTS.system_prompt)}
                className="text-[11px] font-semibold text-indigo-600 hover:underline"
              >
                Khôi phục mặc định
              </button>
            </div>
            <textarea
              rows={3}
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              className={inputCls}
              placeholder="Nhập hướng dẫn vai trò và phong cách cho AI..."
            />
          </div>

          {/* Row 3: Title, Description, Hashtag Prompt Rules */}
          <div className="grid gap-4 sm:grid-cols-3">
            <div>
              <label className={labelCls}>Quy tắc Tiêu đề (Title Prompt)</label>
              <textarea
                rows={3}
                value={titlePrompt}
                onChange={(e) => setTitlePrompt(e.target.value)}
                className={inputCls}
                placeholder="Quy tắc tạo tiêu đề..."
              />
              <p className="mt-1 text-[11px] text-slate-400">Độ dài tiêu đề, kích thích click.</p>
            </div>

            <div>
              <label className={labelCls}>Quy tắc Mô tả (Description Prompt)</label>
              <textarea
                rows={3}
                value={descriptionPrompt}
                onChange={(e) => setDescriptionPrompt(e.target.value)}
                className={inputCls}
                placeholder="Quy tắc tạo mô tả..."
              />
              <p className="mt-1 text-[11px] text-slate-400">Số đoạn văn, lời kêu gọi hành động.</p>
            </div>

            <div>
              <label className={labelCls}>Quy tắc Hashtag (Hashtag Prompt)</label>
              <textarea
                rows={3}
                value={hashtagPrompt}
                onChange={(e) => setHashtagPrompt(e.target.value)}
                className={inputCls}
                placeholder="Quy tắc chọn hashtag..."
              />
              <p className="mt-1 text-[11px] text-slate-400">Cách chọn tag liên quan nội dung.</p>
            </div>
          </div>

          {/* Row 4: Language, Tone, Max Hashtags & Emoji */}
          <div className="grid gap-4 sm:grid-cols-4">
            <div>
              <label className={labelCls}>Ngôn ngữ đầu ra</label>
              <select
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                className={inputCls}
              >
                {LANGUAGES.map((l) => (
                  <option key={l.value} value={l.value}>
                    {l.label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className={labelCls}>Giọng văn (Tone)</label>
              <select
                value={tone}
                onChange={(e) => setTone(e.target.value)}
                className={inputCls}
              >
                {TONES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className={labelCls}>Số hashtag tối đa</label>
              <input
                type="number"
                min={1}
                max={30}
                value={maxHashtags}
                onChange={(e) => setMaxHashtags(parseInt(e.target.value, 10) || 10)}
                className={inputCls}
              />
            </div>

            <div className="flex flex-col justify-end pb-1.5">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={includeEmojis}
                  onChange={(e) => setIncludeEmojis(e.target.checked)}
                  className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                />
                <span className="text-xs font-bold text-slate-700">Sử dụng Emoji sinh động</span>
              </label>
            </div>
          </div>

          {/* Row 5: Required & Forbidden Keywords */}
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className={labelCls}>Từ khóa BẮT BUỘC có (Phân cách bởi dấu phẩy)</label>
              <input
                type="text"
                value={requiredKeywords}
                onChange={(e) => setRequiredKeywords(e.target.value)}
                className={inputCls}
                placeholder="vd: Liên Quân, Highlight, Citra"
              />
              <p className="mt-1 text-[11px] text-slate-400">AI sẽ luôn lồng ghép các từ khóa này.</p>
            </div>

            <div>
              <label className={labelCls}>Từ khóa CẤM (Phân cách bởi dấu phẩy)</label>
              <input
                type="text"
                value={forbiddenKeywords}
                onChange={(e) => setForbiddenKeywords(e.target.value)}
                className={inputCls}
                placeholder="vd: cờ bạc, lừa đảo, thô tục"
              />
              <p className="mt-1 text-[11px] text-slate-400">AI tuyệt đối không xuất hiện các từ này.</p>
            </div>
          </div>

          {/* Row 6: Locked Hashtags */}
          <div>
            <label className={labelCls}>Hashtag cố định (Luôn đính kèm theo video)</label>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              {lockedHashtags.map((tag) => (
                <span
                  key={tag}
                  className="inline-flex items-center gap-1 rounded-xl bg-indigo-50 px-3 py-1 text-xs font-bold text-indigo-700 border border-indigo-200"
                >
                  {tag}
                  <button
                    type="button"
                    onClick={() => handleRemoveTag(tag)}
                    className="ml-1 text-indigo-400 hover:text-indigo-900"
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>

            <div className="mt-2.5 flex items-center gap-2 max-w-sm">
              <input
                type="text"
                value={tagInput}
                onChange={(e) => setTagInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    handleAddTag();
                  }
                }}
                className={`${inputCls} text-xs py-1.5`}
                placeholder="#thegioididong"
              />
              <button
                type="button"
                onClick={handleAddTag}
                className={btnSmall}
              >
                Thêm tag
              </button>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-5">
            <button
              type="button"
              onClick={() => setShowTest(!showTest)}
              className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-xs font-bold text-slate-700 shadow-sm transition hover:bg-slate-100"
            >
              <IconSparkles size={15} />
              {showTest ? "Đóng kiểm tra thử nghiệm" : "Kiểm tra thử nghiệm AI (Test AI)"}
            </button>

            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              className={`${btnPrimary} min-h-[44px] px-6 text-sm`}
            >
              {saving ? <Spinner size={15} /> : <IconCheck size={16} />}
              <span>{saving ? "Đang lưu..." : "Lưu cài đặt AI"}</span>
            </button>
          </div>
        </div>
      </Card>

      {/* Live Test AI Drawer / Card */}
      {showTest && (
        <Card>
          <CardHeader
            title="Thử nghiệm sinh nội dung AI (Test AI)"
            subtitle="Xem trước tiêu đề, mô tả và hashtag được sinh theo cấu hình hiện tại mà không đăng video"
            icon={<IconSparkles size={18} />}
          />
          <div className="space-y-4 p-4 sm:p-6">
            <div>
              <label className={labelCls}>Mô tả / Caption video mẫu từ TikTok</label>
              <textarea
                rows={2}
                value={testCaption}
                onChange={(e) => setTestCaption(e.target.value)}
                className={inputCls}
                placeholder="Nhập caption mẫu của video TikTok..."
              />
            </div>

            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={handleRunTest}
                disabled={testing}
                className={`${btnPrimary} text-xs`}
              >
                {testing ? <Spinner size={14} /> : <IconSparkles size={14} />}
                <span>{testing ? "AI đang sinh nội dung..." : "Chạy thử nghiệm AI ngay"}</span>
              </button>
            </div>

            {testError && (
              <div className="rounded-xl bg-rose-50 p-3 text-xs text-rose-700 border border-rose-200">
                {testError}
              </div>
            )}

            {testResult && (
              <div className="space-y-3 rounded-2xl bg-slate-50 p-4 border border-slate-200">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
                    Kết quả xem trước
                  </span>
                  <Badge tone="green">Thành công</Badge>
                </div>

                <div>
                  <span className="text-xs font-bold text-slate-500">Tiêu đề YouTube:</span>
                  <p className="mt-0.5 text-sm font-extrabold text-slate-900">{testResult.title}</p>
                </div>

                <div>
                  <span className="text-xs font-bold text-slate-500">Mô tả YouTube:</span>
                  <p className="mt-0.5 whitespace-pre-line text-xs text-slate-700">{testResult.description}</p>
                </div>

                <div>
                  <span className="text-xs font-bold text-slate-500">Hashtags:</span>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {testResult.hashtags.map((tag) => (
                      <span key={tag} className="rounded-lg bg-indigo-100 px-2 py-0.5 text-xs font-bold text-indigo-700">
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        </Card>
      )}
    </div>
  );
}
