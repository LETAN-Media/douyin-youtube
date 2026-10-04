"use client";

import { useState } from "react";
import { Card, CardHeader, Badge, btnSmall } from "@/components/ui";
import { IconSources } from "@/components/icons";
import type { FacebookSourceDto } from "@/lib/facebook-api";

function sourceStatus(s: FacebookSourceDto): { tone: string; label: string } {
  if (s.last_scan_status === "failed") return { tone: "red", label: "Error" };
  if (s.last_scan_status === "running" || s.last_scan_status === "queued") {
    return { tone: "amber", label: "Scanning" };
  }
  return { tone: "green", label: "Connected" };
}

export function FacebookSources({ sources }: { sources: FacebookSourceDto[] }) {
  const [scanning, setScanning] = useState<Record<string, string>>({});

  async function scanNow(sourceId: string) {
    setScanning((m) => ({ ...m, [sourceId]: "starting" }));
    try {
      const res = await fetch("/api/facebook/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sourceId }),
      });
      const data = (await res.json()) as { error?: string };
      setScanning((m) => ({
        ...m,
        [sourceId]: res.ok ? "started" : `error: ${data.error ?? res.status}`,
      }));
    } catch {
      setScanning((m) => ({ ...m, [sourceId]: "error: network" }));
    }
  }

  return (
    <Card>
      <CardHeader
        title={`Facebook Sources (${sources.length})`}
        subtitle="Quản lý Fanpage nguồn cho pipeline này"
        icon={<IconSources size={16} />}
      />
      {sources.length === 0 ? (
        <div className="p-6 text-center text-sm text-slate-500">Chưa có Facebook source</div>
      ) : (
        <div className="space-y-3 p-4 sm:px-5">
          {sources.map((s) => {
            const st = sourceStatus(s);
            const state = scanning[s.id];
            return (
              <div key={s.id} className="rounded-2xl border border-slate-200/90 bg-white p-4 shadow-[0_1px_2px_rgba(15,23,42,0.05)]">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-extrabold text-slate-900">Facebook Page</p>
                    <p className="mt-1 text-xs text-slate-500">Fanpage: {s.page_name ?? "—"}</p>
                    <p className="text-xs text-slate-500">Page ID: {s.page_id}</p>
                    {s.reels_url ? (
                      <p className="truncate text-xs text-slate-400">{s.reels_url}</p>
                    ) : null}
                  </div>
                  <Badge tone={st.tone} dot>
                    {st.label}
                  </Badge>
                </div>
                <div className="mt-3 flex flex-wrap gap-3 text-xs text-slate-600">
                  <span>Enabled: {s.enabled ? "ON" : "OFF"}</span>
                  <span>
                    Last Scan: {s.last_scan_at ? new Date(s.last_scan_at).toLocaleString() : "—"}
                  </span>
                  <span>Status: {s.last_scan_status ?? "—"}</span>
                  <span>Videos Found: {s.discovered_total}</span>
                  {s.crawl_complete ? <span>Crawl: complete</span> : null}
                </div>
                {s.last_scan_error ? (
                  <p className="mt-2 text-xs text-rose-600">{s.last_scan_error}</p>
                ) : null}
                <div className="mt-3 flex flex-wrap gap-1.5">
                  <button
                    type="button"
                    className={btnSmall}
                    disabled={!s.enabled || state === "starting"}
                    onClick={() => scanNow(s.id)}
                  >
                    {state === "starting" ? "Đang bắt đầu…" : "Quét ngay"}
                  </button>
                </div>
                {state && state !== "starting" ? (
                  <p className="mt-2 text-xs text-slate-500">
                    {state === "started" ? "Đã xếp hàng scan." : state}
                  </p>
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}
