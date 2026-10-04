"use client";

import { Card, CardHeader, Badge } from "@/components/ui";
import { IconSparkles } from "@/components/icons";

// AI metadata is not implemented on the backend yet.
// Show an honest not-configured state instead of fake settings.
export function FacebookAiProcessing() {
  return (
    <Card>
      <CardHeader
        title="AI Processing"
        subtitle="Cấu hình metadata AI cho Facebook → YouTube"
        icon={<IconSparkles size={16} />}
      />
      <div className="grid gap-3 p-4 sm:px-5">
        <div className="flex items-center justify-between rounded-xl border border-slate-100 bg-white px-3 py-2.5">
          <span className="text-xs font-bold text-slate-700">AI metadata</span>
          <Badge tone="slate">Not configured</Badge>
        </div>
        <p className="text-xs text-slate-500">
          AI metadata chưa được cấu hình. Video hiện dùng caption gốc từ Facebook.
        </p>
      </div>
    </Card>
  );
}
