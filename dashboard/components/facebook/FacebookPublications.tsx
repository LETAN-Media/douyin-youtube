"use client";

import { Card, CardHeader, Badge, btnSmall } from "@/components/ui";
import { IconPublications } from "@/components/icons";
import type { FacebookPublication } from "@/lib/facebook-mock";

export function FacebookPublications({ publications }: { publications: FacebookPublication[] }) {
  return (
    <Card>
      <CardHeader
        title={`Publications (${publications.length})`}
        subtitle="Lịch sử đăng video từ Facebook lên YouTube"
        icon={<IconPublications size={16} />}
      />
      {publications.length === 0 ? (
        <div className="p-6 text-center text-sm text-slate-500">Chưa có publication</div>
      ) : (
        <div className="space-y-3 p-4 sm:px-5">
          {publications.map((p) => (
            <div key={p.id} className="rounded-2xl border border-slate-200/90 bg-white p-4 shadow-[0_1px_2px_rgba(15,23,42,0.05)]">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-bold text-slate-900">
                    {p.facebookVideoId} → {p.youtubeVideoId || "..."}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    Published: {p.publishedAt ? new Date(p.publishedAt).toLocaleString() : "—"}
                  </p>
                  {p.error ? (
                    <p className="mt-1 text-xs text-rose-600">{p.error}</p>
                  ) : null}
                </div>
                <Badge tone={p.status === "published" ? "green" : p.status === "failed" ? "red" : "amber"}>
                  {p.status}
                </Badge>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
