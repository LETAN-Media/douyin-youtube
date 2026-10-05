"use client";

import { useState } from "react";
import { Card, CardHeader, Badge, btnSmall, inputCls, labelCls } from "@/components/ui";
import { IconDestinations, IconPlus, IconCheck } from "@/components/icons";
import type { FacebookDestinationDto } from "@/lib/facebook-api";
import { listFacebookDestinations } from "@/lib/facebook-api";

export function FacebookDestinations({
  pipelineId,
  initial,
}: {
  pipelineId: string;
  initial: FacebookDestinationDto[];
}) {
  const [destinations, setDestinations] = useState<FacebookDestinationDto[]>(initial);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [authUrls, setAuthUrls] = useState<Record<string, string>>({});
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newDestVisibility, setNewDestVisibility] = useState("private");
  const [newDestEnabled, setNewDestEnabled] = useState(true);

  async function refreshDestinations() {
    try {
      const list = await listFacebookDestinations(pipelineId);
      setDestinations(list);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không tải được danh sách destination.");
    }
  }

  async function createDestination() {
    setCreating(true);
    setError(null);
    try {
      const res = await fetch(`/api/facebook/pipelines/${encodeURIComponent(pipelineId)}/youtube-destinations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ visibility: newDestVisibility, enabled: newDestEnabled }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? `HTTP ${res.status}`);
      await refreshDestinations();
      setShowCreate(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không tạo được destination.");
    } finally {
      setCreating(false);
    }
  }

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
      {!showCreate ? (
        <div className="space-y-3 p-4 sm:px-5">
          {destinations.length === 0 ? (
            <div className="p-6 text-center text-sm text-slate-500">Chưa có destination</div>
          ) : (
            <div className="space-y-3">
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
          <button type="button" className={btnSmall} onClick={() => setShowCreate(true)}>
            <IconPlus size={14} className="mr-1" />
            Tạo YouTube Destination mới
          </button>
        </div>
      ) : (
        <div className="space-y-3 p-4 sm:px-5 border-t border-slate-100">
          <p className="text-sm font-semibold text-slate-900">Tạo YouTube Destination mới</p>
          <div>
            <label className={labelCls}>Visibility</label>
            <select value={newDestVisibility} onChange={(e) => setNewDestVisibility(e.target.value)} className={inputCls}>
              <option value="private">Private (chỉ mình bạn)</option>
              <option value="unlisted">Unlisted (có link mới xem được)</option>
              <option value="public">Public (công khai)</option>
            </select>
          </div>
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={newDestEnabled}
              onChange={(e) => setNewDestEnabled(e.target.checked)}
              className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
            />
            <label className="text-sm font-medium text-slate-700">Enabled</label>
          </div>
          <div className="flex gap-1.5">
            <button
              type="button"
              className={`flex items-center gap-1 ${btnSmall}`}
              disabled={creating}
              onClick={createDestination}
            >
              {creating ? (
                <>
                  <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" /></svg>
                  Đang tạo…
                </>
              ) : (
                <>
                  <IconPlus size={14} className="mr-1" />
                  Tạo destination
                </>
              )}
            </button>
            <button type="button" className={btnSmall} onClick={() => setShowCreate(false)} disabled={creating}>
              Hủy
            </button>
          </div>
        </div>
      )}
    </Card>
  );
}
