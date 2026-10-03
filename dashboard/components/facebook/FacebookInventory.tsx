"use client";

import { Card, CardHeader, Badge, btnSmall } from "@/components/ui";
import { IconInventory } from "@/components/icons";
import type { FacebookInventoryItem } from "@/lib/facebook-mock";

const STATUS_TONE: Record<string, string> = {
  new: "slate",
  queued: "amber",
  processing: "indigo",
  ready: "green",
  uploaded: "green",
  failed: "red",
};

export function FacebookInventory({ items }: { items: FacebookInventoryItem[] }) {
  return (
    <Card>
      <CardHeader
        title={`Inventory (${items.length})`}
        subtitle="Video từ Facebook Fanpage"
        icon={<IconInventory size={16} />}
      />
      {items.length === 0 ? (
        <div className="p-6 text-center text-sm text-slate-500">Inventory trống</div>
      ) : (
        <>
          <div className="hidden overflow-x-auto md:block">
            <table className="w-full text-sm">
              <thead className="bg-slate-50/70">
                <tr className="border-b border-slate-100 text-left text-[11px] uppercase tracking-[0.08em] text-slate-400">
                  <th className="px-5 py-3 font-bold">Video</th>
                  <th className="px-3 py-3 font-bold">Facebook ID</th>
                  <th className="px-3 py-3 font-bold">Duration</th>
                  <th className="px-3 py-3 font-bold">Status</th>
                  <th className="px-3 py-3 font-bold">YouTube ID</th>
                  <th className="px-3 py-3 text-right font-bold">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {items.map((v) => (
                  <tr key={v.id} className="transition hover:bg-indigo-50/40">
                    <td className="max-w-md px-5 py-3">
                      <p className="truncate font-bold text-slate-900">{v.title}</p>
                    </td>
                    <td className="whitespace-nowrap px-3 py-3 text-xs text-slate-600">{v.facebookVideoId}</td>
                    <td className="whitespace-nowrap px-3 py-3 text-xs text-slate-600">{v.duration}</td>
                    <td className="px-3 py-3">
                      <Badge tone={STATUS_TONE[v.status] ?? "slate"}>{v.status}</Badge>
                    </td>
                    <td className="whitespace-nowrap px-3 py-3 text-xs text-slate-600">{v.youtubeVideoId ?? "—"}</td>
                    <td className="px-5 py-3">
                      <div className="flex justify-end gap-1.5">
                        <button type="button" className={btnSmall} disabled>Detail</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="grid gap-3 p-4 md:hidden">
            {items.map((v) => (
              <div key={v.id} className="rounded-2xl border border-slate-200/90 bg-white p-3.5 shadow-[0_1px_2px_rgba(15,23,42,0.05)]">
                <div className="flex items-center justify-between gap-2">
                  <p className="truncate text-sm font-bold text-slate-900">{v.title}</p>
                  <Badge tone={STATUS_TONE[v.status] ?? "slate"}>{v.status}</Badge>
                </div>
                <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">
                  <span>FB: {v.facebookVideoId}</span>
                  <span>Duration: {v.duration}</span>
                  <span>YT: {v.youtubeVideoId ?? "—"}</span>
                </div>
                <div className="mt-3">
                  <button type="button" className={`${btnSmall} w-full`} disabled>Detail</button>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </Card>
  );
}
