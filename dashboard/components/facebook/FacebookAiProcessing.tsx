"use client";

import { Card, CardHeader, Badge } from "@/components/ui";
import { IconSparkles } from "@/components/icons";
import type { FacebookAiMetadataDto, FacebookAiStatsDto } from "@/lib/facebook-api";

export function FacebookAiProcessing({
  stats,
  sample,
}: {
  stats: FacebookAiStatsDto;
  sample: FacebookAiMetadataDto | null;
}) {
  return (
    <Card>
      <CardHeader
        title="AI Processing"
        subtitle="Metadata YouTube tạo bởi ToolNet AI"
        icon={<IconSparkles size={16} />}
      />
      <div className="grid gap-3 p-4 sm:px-5">
        <div className="grid grid-cols-3 gap-2 text-center">
          {[
            { l: "Generated", v: stats.generated },
            { l: "Pending", v: stats.pending },
            { l: "Failed", v: stats.failed },
          ].map((s) => (
            <div key={s.l} className="rounded-xl bg-slate-50 px-2 py-2.5">
              <dt className="text-[10px] font-bold uppercase tracking-wider text-slate-400">{s.l}</dt>
              <dd className="tnum mt-0.5 text-lg font-extrabold text-slate-900">{s.v}</dd>
            </div>
          ))}
        </div>
        {sample ? (
          <div className="rounded-xl border border-slate-100 bg-white px-3 py-2.5">
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-bold text-slate-700">Mẫu đã generate</span>
              <Badge tone="indigo">{sample.model ?? "AI"}</Badge>
            </div>
            <p className="mt-2 text-sm font-bold text-slate-900">{sample.metadata.title}</p>
            {sample.metadata.description ? (
              <p className="mt-1 line-clamp-3 text-xs text-slate-500">{sample.metadata.description}</p>
            ) : null}
            {sample.metadata.hashtags.length > 0 ? (
              <p className="mt-1.5 text-xs font-semibold text-indigo-600">
                {sample.metadata.hashtags.join(" ")}
              </p>
            ) : null}
          </div>
        ) : (
          <p className="text-xs text-slate-500">
            Chưa có metadata nào được generate. Dùng endpoint admin để tạo cho từng Reel.
          </p>
        )}
      </div>
    </Card>
  );
}
