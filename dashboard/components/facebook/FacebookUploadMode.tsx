"use client";

import { useEffect, useState } from "react";
import { Card, CardHeader } from "@/components/ui";
import { IconUpload } from "@/components/icons";

type UploadMode = "video" | "shorts";

export function FacebookUploadMode({ pipelineId }: { pipelineId: string }) {
  const [mode, setMode] = useState<UploadMode | null>(null);
  const [savedMode, setSavedMode] = useState<UploadMode | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(
          `/api/facebook/pipelines/${encodeURIComponent(pipelineId)}`,
          { cache: "no-store" },
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const current =
          data.youtube_upload_mode === "shorts" ? "shorts" : "video";
        if (!cancelled) {
          setMode(current);
          setSavedMode(current);
        }
      } catch (err) {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : "Không tải được chế độ đăng.");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pipelineId]);

  async function handleSave() {
    if (!mode || saving) return;
    setSaving(true);
    setMessage(null);
    try {
      const res = await fetch(
        `/api/facebook/pipelines/${encodeURIComponent(pipelineId)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ youtube_upload_mode: mode }),
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
      const current =
        data.youtube_upload_mode === "shorts" ? "shorts" : "video";
      setMode(current);
      setSavedMode(current);
      setMessage("Đã lưu chế độ đăng. Áp dụng cho các batch mới.");
      setTimeout(() => setMessage(null), 4000);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Không lưu được chế độ đăng.");
    } finally {
      setSaving(false);
    }
  }

  const dirty = mode !== null && savedMode !== null && mode !== savedMode;

  return (
    <Card>
      <CardHeader
        title="Chế độ đăng YouTube"
        subtitle="Áp dụng cho các batch mới xếp hàng"
        icon={<IconUpload size={16} />}
      />
      <div className="space-y-3 p-4 sm:px-5">
        {loadError ? (
          <p className="text-xs text-rose-600">{loadError}</p>
        ) : mode === null ? (
          <p className="text-xs text-slate-500">Đang tải chế độ đăng…</p>
        ) : (
          <>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {(
                [
                  {
                    value: "video",
                    label: "Video thường",
                    desc: "Đăng nguyên bản, không kiểm tra hay cắt gì thêm.",
                  },
                  {
                    value: "shorts",
                    label: "YouTube Shorts",
                    desc: "Chỉ đăng file dọc/vuông ≤ 3 phút, kiểm tra bằng ffprobe trước khi đăng.",
                  },
                ] as Array<{ value: UploadMode; label: string; desc: string }>
              ).map((opt) => {
                const active = mode === opt.value;
                return (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => setMode(opt.value)}
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
                      {opt.label}
                    </span>
                    <span className="mt-1 block text-xs leading-relaxed text-slate-500">
                      {opt.desc}
                    </span>
                  </button>
                );
              })}
            </div>
            {mode === "shorts" ? (
              <p className="rounded-xl bg-amber-50 p-2.5 text-[11px] leading-relaxed text-amber-800 ring-1 ring-inset ring-amber-100">
                File không đủ điều kiện (dài quá 3 phút hoặc video ngang) sẽ báo lỗi rõ ràng
                chứ không bị cắt. Lưu ý: YouTube vẫn có thể tự phân loại file dọc ngắn
                thành Shorts ngay cả ở chế độ Video thường.
              </p>
            ) : null}
            {message ? (
              <p
                className={`text-xs font-semibold ${
                  message.startsWith("Đã lưu") ? "text-emerald-600" : "text-rose-600"
                }`}
              >
                {message}
              </p>
            ) : null}
            <button
              type="button"
              onClick={() => void handleSave()}
              disabled={saving || !dirty}
              className="inline-flex min-h-[44px] items-center rounded-2xl bg-indigo-600 px-5 py-2.5 text-sm font-extrabold text-white shadow-sm transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {saving ? "Đang lưu…" : "Lưu chế độ đăng"}
            </button>
          </>
        )}
      </div>
    </Card>
  );
}
