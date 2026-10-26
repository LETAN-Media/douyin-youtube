"use client";

import { useEffect, useState } from "react";
import { Badge, Card, CardHeader, Spinner, btnPrimary, btnSecondary } from "@/components/ui";
import { IconCheck, IconFilm, IconUpload, IconVideo } from "@/components/icons";

type UploadMode = "shorts" | "video" | "both";

interface Props {
  pipelineId: string;
  initialMode?: UploadMode;
  onModeChange?: (mode: UploadMode) => void;
}

export function TikTokPublishSettings({ pipelineId, initialMode = "shorts", onModeChange }: Props) {
  const [mode, setMode] = useState<UploadMode>(initialMode);
  const [savedMode, setSavedMode] = useState<UploadMode>(initialMode);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`/api/tiktok/pipelines/${encodeURIComponent(pipelineId)}`);
        if (!res.ok) return;
        const data = await res.json();
        const m = data.youtube_upload_mode === "video" ? "video" : data.youtube_upload_mode === "both" ? "both" : "shorts";
        if (!cancelled) {
          setMode(m);
          setSavedMode(m);
        }
      } catch {
        // use initial
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pipelineId]);

  async function handleSave() {
    if (saving) return;
    setSaving(true);
    setMessage(null);
    try {
      const res = await fetch(`/api/tiktok/pipelines/${encodeURIComponent(pipelineId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ youtube_upload_mode: mode }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.message || data.error || "Không thể lưu cài đặt định dạng.");
      }
      setSavedMode(mode);
      onModeChange?.(mode);
      setMessage({ type: "success", text: "Đã cập nhật định dạng xuất bản thành công." });
    } catch (err: unknown) {
      setMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Lỗi khi lưu cài đặt.",
      });
    } finally {
      setSaving(false);
    }
  }

  const options: { id: UploadMode; title: string; subtitle: string; tag: string; desc: string }[] = [
    {
      id: "shorts",
      title: "Shorts Only",
      subtitle: "Chỉ đăng YouTube Shorts",
      tag: "Khuyến nghị cho TikTok",
      desc: "Kiểm tra kỹ bằng ffprobe: thời lượng ≤ 180 giây, tỷ lệ khung hình dọc (9:16) hoặc vuông (1:1). Nếu video ngang hoặc quá 3 phút, hệ thống sẽ cảnh báo lý do và bỏ qua để bảo vệ kênh.",
    },
    {
      id: "video",
      title: "Regular Videos Only",
      subtitle: "Chỉ đăng Video thông thường",
      tag: "Chuẩn YouTube Video",
      desc: "Đăng tải video dưới dạng thông thường của YouTube, phù hợp với các video tổng hợp, nội dung ngang hoặc clip dài trên 3 phút.",
    },
    {
      id: "both",
      title: "Both — Shorts & Regular Videos",
      subtitle: "Tự động phân loại Shorts & Video",
      tag: "Linh hoạt",
      desc: "Hệ thống tự động kiểm tra metadata qua ffprobe: video đủ điều kiện sẽ đăng thành Shorts, video ngang/dài sẽ đăng thành Video thường. Mỗi video nguồn chỉ đăng 1 lần duy nhất để chống trùng.",
    },
  ];

  const hasChanges = mode !== savedMode;

  return (
    <Card className="rounded-2xl border border-slate-200/90 bg-white p-5 shadow-sm sm:p-6">
      <CardHeader
        title="Định dạng xuất bản video (Video Publishing Settings)"
        subtitle="Cấu hình định dạng xuất bản YouTube cho toàn bộ Pipeline. Backend sử dụng ffprobe để xác thực kích thước và tỷ lệ thực tế."
      />

      <div className="mt-4 grid grid-cols-1 gap-3.5 sm:grid-cols-3">
        {options.map((opt) => {
          const isSelected = mode === opt.id;
          return (
            <button
              key={opt.id}
              type="button"
              onClick={() => setMode(opt.id)}
              className={`flex flex-col justify-between rounded-xl border p-4 text-left transition-all ${
                isSelected
                  ? "border-indigo-600 bg-indigo-50/50 shadow-sm ring-1 ring-indigo-600"
                  : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50/60"
              }`}
            >
              <div>
                <div className="flex items-center justify-between gap-2">
                  <span className="font-bold text-slate-900 text-sm">{opt.title}</span>
                  {isSelected && (
                    <span className="flex h-5 w-5 items-center justify-center rounded-full bg-indigo-600 text-white">
                      <IconCheck size={12} />
                    </span>
                  )}
                </div>
                <p className="mt-1 text-xs font-semibold text-indigo-700">{opt.subtitle}</p>
                <div className="mt-2">
                  <span className="inline-block rounded-md bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600">
                    {opt.tag}
                  </span>
                </div>
                <p className="mt-2.5 text-xs text-slate-600 leading-relaxed">{opt.desc}</p>
              </div>
            </button>
          );
        })}
      </div>

      {message && (
        <div
          className={`mt-4 rounded-xl border p-3 text-xs font-semibold ${
            message.type === "success"
              ? "border-emerald-200 bg-emerald-50 text-emerald-800"
              : "border-rose-200 bg-rose-50 text-rose-800"
          }`}
        >
          {message.text}
        </div>
      )}

      <div className="mt-5 flex items-center justify-between border-t border-slate-100 pt-4">
        <p className="text-xs text-slate-500">
          Chế độ hiện tại: <span className="font-semibold text-slate-800 uppercase">{savedMode}</span>
        </p>
        <button
          type="button"
          disabled={!hasChanges || saving}
          onClick={handleSave}
          className={`${btnPrimary} min-h-[38px] px-4 text-xs font-bold disabled:opacity-50`}
        >
          {saving ? (
            <span className="inline-flex items-center gap-1.5">
              <Spinner size={14} />
              Đang lưu...
            </span>
          ) : (
            "Lưu cài đặt định dạng"
          )}
        </button>
      </div>
    </Card>
  );
}
