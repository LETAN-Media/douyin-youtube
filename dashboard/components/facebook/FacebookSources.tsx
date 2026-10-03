"use client";

import { Card, CardHeader, Badge, btnSmall } from "@/components/ui";
import { IconSources } from "@/components/icons";
import type { FacebookSource } from "@/lib/facebook-mock";

export function FacebookSources({ sources }: { sources: FacebookSource[] }) {
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
          {sources.map((s) => (
            <div key={s.sourceId} className="rounded-2xl border border-slate-200/90 bg-white p-4 shadow-[0_1px_2px_rgba(15,23,42,0.05)]">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-extrabold text-slate-900">Facebook Page</p>
                  <p className="mt-1 text-xs text-slate-500">Fanpage: {s.pageName}</p>
                  <p className="text-xs text-slate-500">Page ID: {s.pageId}</p>
                </div>
                <Badge tone={s.status === "connected" ? "green" : s.status === "scanning" ? "amber" : "red"} dot>
                  {s.status === "connected" ? "Connected" : s.status === "scanning" ? "Scanning" : "Error"}
                </Badge>
              </div>
              <div className="mt-3 flex flex-wrap gap-3 text-xs text-slate-600">
                <span>Auto Scan: {s.autoScan ? "ON" : "OFF"}</span>
                <span>Last Scan: {s.lastScanAt ? new Date(s.lastScanAt).toLocaleTimeString() : "—"}</span>
                <span>Videos Found: {s.videosFound}</span>
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                <button type="button" className={btnSmall}>Đổi Fanpage</button>
                <button type="button" className={btnSmall}>Quét ngay</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
