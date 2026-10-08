"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import type { AudioPipelineDto } from "@/lib/audio-api";
import { AudioTabA } from "./AudioTabsA";
import { AudioTabB } from "./AudioTabsB";

export const AUTO_TABS = [
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

export const MANUAL_TABS = [
  ["manual", "Đăng Video"],
  ["media", "Kho Media"],
  ["processing", "Chế độ xử lý"],
  ["ai", "AI Metadata"],
  ["youtube", "YouTube"],
  ["history", "Lịch sử"],
] as const;

export function AudioPipelineClient({
  pipeline,
  initialTab,
}: {
  pipeline: AudioPipelineDto;
  initialTab: string;
}) {
  const isManual = pipeline.pipeline_type === "manual";
  const tabs = isManual ? MANUAL_TABS : AUTO_TABS;
  const allowedKeys = new Set(tabs.map(([key]) => key as string));

  const searchParams = useSearchParams();
  const [tab, setTab] = useState<string>(() => {
    if (isManual) {
      return allowedKeys.has(initialTab) ? initialTab : "manual";
    }
    return allowedKeys.has(initialTab) ? initialTab : "overview";
  });

  // Watch URL searchParams and sanitize/redirect if forbidden tab on manual
  useEffect(() => {
    const currentTab = searchParams.get("tab");
    if (isManual) {
      if (!currentTab || !allowedKeys.has(currentTab)) {
        setTab("manual");
        if (currentTab && !allowedKeys.has(currentTab)) {
          window.history.replaceState(
            null,
            "",
            `/audio/${encodeURIComponent(pipeline.id)}?tab=manual`
          );
        }
        return;
      }
      setTab(currentTab);
    } else {
      if (currentTab && allowedKeys.has(currentTab)) {
        setTab(currentTab);
      } else if (!currentTab) {
        setTab("overview");
      }
    }
  }, [searchParams, isManual, pipeline.id]);

  // Safe tab determination: ensure forbidden components are NEVER rendered
  const activeTabKey = isManual
    ? (allowedKeys.has(tab) ? tab : "manual")
    : (allowedKeys.has(tab) ? tab : "overview");

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Link
          href={isManual ? "/audio?tab=manual" : "/audio"}
          className="text-xs font-bold text-slate-500 hover:text-slate-800"
        >
          ← Audio
        </Link>
        <h1 className="text-lg font-extrabold text-slate-900">{pipeline.name}</h1>
        {isManual ? (
          <span className="rounded-full bg-amber-100 px-2.5 py-1 text-[11px] font-bold text-amber-800">
            Thủ Công
          </span>
        ) : null}
        <span
          className={`rounded-full px-2.5 py-1 text-[11px] font-bold ${
            pipeline.enabled
              ? "bg-emerald-100 text-emerald-700"
              : "bg-slate-200 text-slate-600"
          }`}
        >
          {pipeline.enabled ? "Bật" : "Tắt"}
        </span>
      </div>

      {/* Tabs navigation */}
      <div className="flex gap-1.5 overflow-x-auto pb-1">
        {tabs.map(([key, label]) => (
          <Link
            key={key}
            href={`/audio/${encodeURIComponent(pipeline.id)}?tab=${key}`}
            onClick={() => setTab(key)}
            className={`whitespace-nowrap rounded-xl px-3 py-2 text-xs font-bold transition-colors ${
              activeTabKey === key
                ? "bg-slate-900 text-white shadow-sm"
                : "bg-white text-slate-600 hover:bg-slate-100"
            }`}
          >
            {label}
          </Link>
        ))}
      </div>

      {/* Tab content rendering with strict guard */}
      {isManual ? (
        activeTabKey === "media" || activeTabKey === "processing" ? (
          <AudioTabA pipeline={pipeline} tab={activeTabKey} />
        ) : (
          <AudioTabB pipeline={pipeline} tab={activeTabKey} />
        )
      ) : (
        ["overview", "sources", "inventory", "media", "processing"].includes(activeTabKey) ? (
          <AudioTabA pipeline={pipeline} tab={activeTabKey} />
        ) : (
          <AudioTabB pipeline={pipeline} tab={activeTabKey} />
        )
      )}
    </div>
  );
}
