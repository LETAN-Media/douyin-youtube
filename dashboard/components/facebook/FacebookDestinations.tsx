"use client";

import { useState } from "react";
import { Card, CardHeader, Badge, btnSmall } from "@/components/ui";
import { IconDestinations } from "@/components/icons";
import type { FacebookDestinationDto } from "@/lib/facebook-api";

export function FacebookDestinations({
  initial,
}: {
  initial: FacebookDestinationDto[];
}) {
  const [destinations] = useState(initial);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [authUrls, setAuthUrls] = useState<Record<string, string>>({});

  async function connect(destinationId: string) {
    setBusy(destinationId);
    setError(null);
    try {
      const res = await fetch("/api/facebook/oauth/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ destinationId }),
      });
      const data = (await res.json()) as { authorization_url?: string; error?: string };
      if (!res.ok || !data.authorization_url) {
        throw new Error(data.error ?? `HTTP ${res.status}`);
      }
      setAuthUrls((m) => ({ ...m, [destinationId]: data.authorization_url as string }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không bắt đầu được OAuth.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card>
      <CardHeader
        title={`Destinations (${destinations.length})`}
        subtitle="YouTube channel đích nhận video từ Facebook"
        icon={<IconDestinations size={16} />}
      />
      {error ? (
        <p className="border-b border-slate-100 px-4 py-2 text-xs text-rose-600 sm:px-5">{error}</p>
      ) : null}
      {destinations.length === 0 ? (
        <div className="p-6 text-center text-sm text-slate-500">Chưa có destination</div>
      ) : (
        <div className="space-y-3 p-4 sm:px-5">
          {destinations.map((d) => (
            <div key={d.id} className="rounded-2xl border border-slate-200/90 bg-white p-4 shadow-[0_1px_2px_rgba(15,23,42,0.05)]">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-extrabold text-slate-900">YouTube Channel</p>
                  <p className="mt-1 text-xs text-slate-500">Channel: {d.channel_name ?? "—"}</p>
                  <p className="text-xs text-slate-500">Channel ID: {d.channel_id ?? "—"}</p>
                </div>
                <Badge tone={d.connected ? "green" : "slate"} dot>
                  {d.connected ? "Connected" : "Not Connected"}
                </Badge>
              </div>
              <div className="mt-3 flex flex-wrap gap-3 text-xs text-slate-600">
                <span>Enabled: {d.enabled ? "ON" : "OFF"}</span>
                <span>Visibility: {d.visibility}</span>
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                <button
                  type="button"
                  className={btnSmall}
                  disabled={busy === d.id}
                  onClick={() => connect(d.id)}
                >
                  {busy === d.id
                    ? "Đang tạo link…"
                    : d.connected
                      ? "Đổi kênh YouTube"
                      : "Kết nối YouTube"}
                </button>
                {authUrls[d.id] ? (
                  <a
                    href={authUrls[d.id]}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={btnSmall}
                  >
                    Tiếp tục tới Google →
                  </a>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
