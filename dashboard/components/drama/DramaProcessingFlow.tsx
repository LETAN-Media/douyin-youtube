"use client";

import type { ProcessingMode } from "./DramaProcessingSettings";

const FLOWS: Record<ProcessingMode, string[]> = {
  direct_merge: ["Tải tập", "Gộp video", "Đăng YouTube"],
  translate_sub: ["Tải tập", "ASR", "Dịch", "Gộp + phụ đề", "Đăng YouTube"],
  dub_vi: ["Tải tập", "ASR", "Dịch", "TTS", "Dựng + gộp", "Đăng YouTube"],
};

export function DramaProcessingFlow({ mode }: { mode: ProcessingMode }) {
  const steps = FLOWS[mode] ?? FLOWS.direct_merge;
  return (
    <div className="rounded-2xl border border-slate-200/90 bg-white p-4 shadow-sm">
      <p className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
        Quy trình
      </p>
      <ol className="mt-3 flex flex-wrap items-center gap-y-2">
        {steps.map((label, i) => (
          <li key={label} className="flex items-center">
            <span className="inline-flex min-h-[32px] items-center gap-2 rounded-full bg-indigo-50 px-3 py-1.5 text-xs font-bold text-indigo-800 ring-1 ring-inset ring-indigo-100">
              <span className="flex h-5 w-5 items-center justify-center rounded-full bg-indigo-600 text-[10px] font-black text-white">
                {i + 1}
              </span>
              {label}
            </span>
            {i < steps.length - 1 ? (
              <span aria-hidden className="mx-1.5 font-black text-slate-300">
                →
              </span>
            ) : null}
          </li>
        ))}
      </ol>
    </div>
  );
}
