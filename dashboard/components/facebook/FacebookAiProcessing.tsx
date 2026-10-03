"use client";

import { Card, CardHeader, Badge, btnSmall } from "@/components/ui";
import { IconSparkles } from "@/components/icons";
import type { FacebookAiSettings } from "@/lib/facebook-mock";

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between rounded-xl border border-slate-100 bg-white px-3 py-2.5">
      <span className="text-xs font-bold text-slate-700">{label}</span>
      <Badge tone={value === "keep" || value === "source" ? "slate" : "indigo"}>{value.replace(/_/g, " ")}</Badge>
    </div>
  );
}

export function FacebookAiProcessing({ settings }: { settings: FacebookAiSettings }) {
  return (
    <Card>
      <CardHeader
        title="AI Processing"
        subtitle="Cấu hình metadata AI cho Facebook → YouTube"
        icon={<IconSparkles size={16} />}
      />
      <div className="grid gap-3 p-4 sm:px-5">
        <Row label="Title mode" value={settings.titleMode} />
        <Row label="Description mode" value={settings.descriptionMode} />
        <Row label="Hashtags mode" value={settings.hashtagsMode} />
        <Row label="Thumbnail mode" value={settings.thumbnailMode} />
        <div className="mt-2 flex flex-wrap gap-1.5">
          <button type="button" className={btnSmall}>Cài đặt</button>
        </div>
      </div>
    </Card>
  );
}
