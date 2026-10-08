"use client";

import Link from "next/link";
import { useState } from "react";
import type { AudioPipelineDto } from "@/lib/audio-api";
import { AudioTabA } from "./AudioTabsA";
import { AudioTabB } from "./AudioTabsB";

const TABS = [
  ["overview", "Tổng quan"],
  ["sources", "Nguồn Facebook"],
  ["inventory", "Inventory"],
  ["media", "Kho Media"],
  ["processing", "Chế độ xử lý"],
  ["ai", "AI Metadata"],
  ["youtube", "YouTube"],
  ["scheduler", "Tự động đăng"],
  ["manual", "Đăng thủ công"],
  ["history", "Lịch sử"],
] as const;

export type AudioTabKey = (typeof TABS)[number][0];

export function AudioPipelineClient({
  pipeline, initialTab,
}: {
  pipeline: AudioPipelineDto;
  initialTab: AudioTabKey;
}) {
  const [tab, setTab] = useState<AudioTabKey>(initialTab);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Link href="/audio" className="text-xs font-bold text-slate-500">
          ← Audio
        </Link>
        <h1 className="text-lg font-extrabold text-slate-900">{pipeline.name}</h1>
        <span className={`rounded-full px-2.5 py-1 text-[11px] font-bold ${
          pipeline.enabled ? "bg-emerald-100 text-emerald-700" : "bg-slate-200 text-slate-600"
        }`}>
          {pipeline.enabled ? "Bật" : "Tắt"}
        </span>
      </div>
      <div className="flex gap-1.5 overflow-x-auto pb-1">
        {TABS.map(([key, label]) => (
          <Link
            key={key}
            href={`/audio/${encodeURIComponent(pipeline.id)}?tab=${key}`}
            onClick={() => setTab(key)}
            className={`whitespace-nowrap rounded-xl px-3 py-2 text-xs font-bold ${
              tab === key ? "bg-slate-900 text-white" : "bg-white text-slate-600 hover:bg-slate-100"
            }`}
          >
            {label}
          </Link>
        ))}
      </div>
      {["overview", "sources", "inventory", "media", "processing"].includes(tab) ? (
        <AudioTabA pipeline={pipeline} tab={tab} />
      ) : (
        <AudioTabB pipeline={pipeline} tab={tab} />
      )}
    </div>
  );
}
