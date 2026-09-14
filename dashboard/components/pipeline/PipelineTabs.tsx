"use client";

import { useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";

export type PipelineTabKey =
  | "overview"
  | "sources"
  | "inventory"
  | "destinations"
  | "publications"
  | "ai-profile"
  | "settings";

const TABS: { key: PipelineTabKey; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "sources", label: "Sources" },
  { key: "inventory", label: "Inventory" },
  { key: "destinations", label: "Destinations" },
  { key: "publications", label: "Publications" },
  { key: "ai-profile", label: "AI Profile" },
  { key: "settings", label: "Settings" },
];

export function PipelineTabs({
  pipelineId,
  activeTab,
}: {
  pipelineId: string;
  activeTab: PipelineTabKey;
}) {
  const router = useRouter();
  const [isPending, start] = useTransition();
  // Optimistic tab: highlights instantly on tap (<100ms), before server responds.
  const [optimistic, setOptimistic] = useState<PipelineTabKey | null>(null);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- clear optimistic on navigation commit
    setOptimistic(null);
  }, [activeTab]);

  const shown = optimistic ?? activeTab;

  const go = (key: PipelineTabKey) => (e: React.MouseEvent) => {
    e.preventDefault();
    if (key === shown && !optimistic) return;
    // Instant UI feedback: no second tap needed.
    setOptimistic(key);
    start(() => {
      router.push(`/pipelines/${pipelineId}?tab=${key}`);
    });
  };

  return (
    <div className="sticky top-14 z-30 -mx-4 mt-4 border-y border-slate-200 bg-[#f1f5f9]/95 px-4 backdrop-blur sm:-mx-6 sm:px-6">
      <nav
        aria-label="Pipeline tabs"
        className="mx-auto flex max-w-7xl gap-1 overflow-x-auto py-2"
      >
        {TABS.map((t) => {
          const active = shown === t.key;
          const pendingThis = isPending && optimistic === t.key;
          return (
            <a
              key={t.key}
              href={`/pipelines/${pipelineId}?tab=${t.key}`}
              onClick={go(t.key)}
              aria-current={active ? "page" : undefined}
              className={`inline-flex min-h-[44px] shrink-0 items-center gap-1.5 rounded-xl px-3 py-2 text-sm font-semibold transition ${
                active
                  ? "bg-indigo-600 text-white"
                  : "text-slate-600 hover:bg-slate-200/70"
              }`}
            >
              {pendingThis ? (
                <span
                  aria-hidden
                  className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/40 border-t-white"
                />
              ) : null}
              {t.label}
            </a>
          );
        })}
        {isPending ? (
          <span className="ml-1 inline-flex min-h-[44px] shrink-0 items-center text-xs font-medium text-slate-400">
            Đang tải…
          </span>
        ) : null}
      </nav>
    </div>
  );
}
