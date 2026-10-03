"use client";

import { Card, CardHeader, Badge, btnSmall } from "@/components/ui";
import { IconDestinations } from "@/components/icons";

export function FacebookDestinations({ pipelineId }: { pipelineId: string }) {
  const destinations = [
    {
      id: `${pipelineId}-yt-1`,
      name: "JoyBeat Dance",
      channelId: "UC_mock_channel_1",
      connected: true,
      autoUpload: true,
      visibility: "public",
      schedule: "Auto / Scheduled",
    },
  ];

  return (
    <Card>
      <CardHeader
        title={`Destinations (${destinations.length})`}
        subtitle="YouTube channel đích nhận video từ Facebook"
        icon={<IconDestinations size={16} />}
      />
      {destinations.length === 0 ? (
        <div className="p-6 text-center text-sm text-slate-500">Chưa có destination</div>
      ) : (
        <div className="space-y-3 p-4 sm:px-5">
          {destinations.map((d) => (
            <div key={d.id} className="rounded-2xl border border-slate-200/90 bg-white p-4 shadow-[0_1px_2px_rgba(15,23,42,0.05)]">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-extrabold text-slate-900">YouTube Channel</p>
                  <p className="mt-1 text-xs text-slate-500">Channel: {d.name}</p>
                  <p className="text-xs text-slate-500">Channel ID: {d.channelId}</p>
                </div>
                <Badge tone={d.connected ? "green" : "slate"} dot>
                  {d.connected ? "Connected" : "Not Connected"}
                </Badge>
              </div>
              <div className="mt-3 flex flex-wrap gap-3 text-xs text-slate-600">
                <span>Auto Upload: {d.autoUpload ? "ON" : "OFF"}</span>
                <span>Visibility: {d.visibility}</span>
                <span>Schedule: {d.schedule}</span>
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                <button type="button" className={btnSmall}>Đổi kênh YouTube</button>
                <button type="button" className={btnSmall}>Cài đặt</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
