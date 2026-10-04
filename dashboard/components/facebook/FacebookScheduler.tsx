"use client";

import { Card, CardHeader, Badge, btnSmall } from "@/components/ui";
import { IconCalendar } from "@/components/icons";
import type { FacebookScheduleStatus } from "@/lib/facebook-api";

const WEEKDAY_NAMES = ["Chủ nhật", "Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7"];

export function FacebookScheduler({
  initialSchedule,
  initialStatus,
}: {
  initialSchedule: any;
  initialStatus: FacebookScheduleStatus;
}) {
  const batchStatus = initialStatus?.batch_status || "idle";
  const scheduledToday = initialStatus?.scheduled_today ?? 0;
  const dailyLimit = initialStatus?.daily_limit ?? 5;
  const slots = initialStatus?.slots || [];

  const slotsByDay = slots.reduce<Record<number, any[]>>((acc, slot: any) => {
    const day = slot.weekday ?? 0;
    acc[day] = acc[day] || [];
    acc[day].push(slot);
    return acc;
  }, {});

  return (
    <Card>
      <CardHeader
        title="Scheduler"
        subtitle="Lịch tự động đăng YouTube"
        icon={<IconCalendar size={16} />}
      />
      <div className="space-y-4 p-4 sm:px-5">
        <div className="flex flex-wrap items-center gap-3">
          <Badge tone={initialSchedule?.enabled ? "green" : "slate"}>
            {initialSchedule?.enabled ? "Auto ON" : "Auto OFF"}
          </Badge>
          <span className="text-xs text-slate-500">
            Timezone: {initialSchedule?.timezone || "Asia/Ho_Chi_Minh"}
          </span>
          <span className="text-xs text-slate-500">
            Batch: {initialSchedule?.batch_time || "06:00"}
          </span>
          <span className="text-xs text-slate-500">
            Max/day: {dailyLimit}
          </span>
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-center">
            <p className="text-xs text-slate-500">Hôm nay</p>
            <p className="text-sm font-bold text-slate-900">
              {WEEKDAY_NAMES[initialStatus?.weekday ?? 0]}
            </p>
          </div>
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-center">
            <p className="text-xs text-slate-500">Batch</p>
            <p className="text-sm font-bold text-slate-900">
              <Badge tone={
                batchStatus === "completed" ? "green" :
                batchStatus === "running" ? "amber" :
                batchStatus === "failed" ? "red" :
                "slate"
              }>
                {batchStatus}
              </Badge>
            </p>
          </div>
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-center">
            <p className="text-xs text-slate-500">Scheduled</p>
            <p className="text-sm font-bold text-slate-900">
              {scheduledToday}/{dailyLimit}
            </p>
          </div>
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-center">
            <p className="text-xs text-slate-500">Next batch</p>
            <p className="text-sm font-bold text-slate-900">
              {initialStatus?.next_batch_at
                ? new Date(initialStatus.next_batch_at).toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" })
                : "—"}
            </p>
          </div>
        </div>

        <div>
          <p className="mb-2 text-xs font-semibold text-slate-500 uppercase tracking-wider">Lịch tuần</p>
          <div className="space-y-2">
            {Object.entries(slotsByDay)
              .sort(([a], [b]) => Number(a) - Number(b))
              .map(([day, daySlots]) => (
                <div key={day} className="flex items-center gap-2 rounded-xl border border-slate-100 bg-white p-2">
                  <span className="w-20 shrink-0 text-xs font-bold text-slate-600">
                    {WEEKDAY_NAMES[Number(day)]}
                  </span>
                  <div className="flex flex-wrap gap-1.5">
                    {(daySlots as any[]).map((slot: any) => {
                      const time = slot.time || slot.slot_time || "";
                      return (
                        <span
                          key={time}
                          className="rounded-lg bg-indigo-50 px-2 py-1 text-xs font-semibold text-indigo-700"
                        >
                          {time}
                        </span>
                      );
                    })}
                  </div>
                </div>
              ))}
          </div>
        </div>
      </div>
    </Card>
  );
}
