"use client";

import { useState } from "react";
import { Card, CardHeader, Badge, btnSmall, inputCls, labelCls } from "@/components/ui";
import { IconDestinations, IconPlus } from "@/components/icons";
import type { FacebookDestinationDto } from "@/lib/facebook-api";

function friendlyError(status: number | null, serverMessage: string | null, fallback: string): string {
  const msg = (serverMessage ?? "").trim();
  if (status === 400) return msg || "Yêu cầu không hợp lệ.";
  if (status === 401) return "Backend Facebook authentication failed.";
  if (status === 403) return msg || "Không có quyền thực hiện thao tác.";
  if (status === 404) return "Không tìm thấy pipeline.";
  if (status !== null && status >= 500) return msg || "Không thể tạo kênh đích.";
  return msg || fallback;
}

async function parseErrorMessage(res: Response): Promise<string | null> {
  try {
    const data = (await res.json()) as { error?: unknown; message?: unknown };
    if (typeof data?.error === "string" && data.error.trim()) return data.error;
    if (typeof data?.message === "string" && data.message.trim()) return data.message;
    return null;
  } catch {
    return null;
  }
}

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
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [creating, setCreating] = useState(false);
  // Intended final visibility is public: scheduler uploads private first,
  // YouTube flips to public at publishAt.
  const [newDestVisibility, setNewDestVisibility] = useState("public");
  const [newDestEnabled, setNewDestEnabled] = useState(true);

  function proxyUrl() {
    return `/api/facebook/pipelines/${encodeURIComponent(pipelineId)}/youtube-destinations`;
  }

  async function refreshDestinations() {
    try {
      const res = await fetch(proxyUrl(), { cache: "no-store" });
      if (!res.ok) {
        const serverMessage = await parseErrorMessage(res);
        throw new Error(friendlyError(res.status, serverMessage, "Không tải được danh sách kênh YouTube."));
      }
      const list = (await res.json()) as FacebookDestinationDto[];
      setDestinations(Array.isArray(list) ? list : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không tải được danh sách kênh YouTube.");
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
      const data = (await res.json()) as { authorization_url?: string; error?: string; message?: string };
      if (!res.ok || !data.authorization_url) {
        const serverMessage =
          (typeof data.error === "string" && data.error) ||
          (typeof data.message === "string" && data.message) ||
          null;
        throw new Error(friendlyError(res.status, serverMessage, "Không bắt đầu được OAuth."));
      }
      setAuthUrls((m) => ({ ...m, [destinationId]: data.authorization_url as string }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không bắt đầu được OAuth.");
    } finally {
      setBusy(null);
    }
  }

  // Create a destination, then immediately start OAuth so the user
  // lands on Google consent in one flow (no extra click needed).
  async function createAndConnect() {
    setCreating(true);
    setError(null);
    try {
      const res = await fetch(proxyUrl(), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ visibility: newDestVisibility, enabled: newDestEnabled }),
      });
      if (!res.ok) {
        const serverMessage = await parseErrorMessage(res);
        throw new Error(
          friendlyError(
            res.status,
            serverMessage,
            res.status === 404 ? "Không tìm thấy pipeline." : "Không thể tạo kênh đích.",
          ),
        );
      }
      const created = (await res.json()) as FacebookDestinationDto;
      if (created && typeof created === "object" && "id" in created) {
        setDestinations((prev) =>
          prev.some((d) => d.id === created.id) ? prev : [...prev, created],
        );
        setShowAdvanced(false);
        await connect(created.id);
      } else {
        await refreshDestinations();
        setShowAdvanced(false);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không thể tạo kênh đích.");
    } finally {
      setCreating(false);
    }
  }

  // Duplicate safety: if a pending (not connected) destination already
  // exists, reuse it for OAuth instead of creating another one.
  async function handlePrimaryConnect() {
    const pending = destinations.find((d) => !d.connected);
    if (pending) {
      await connect(pending.id);
      return;
    }
    await createAndConnect();
  }

  const pendingDestination = destinations.find((d) => !d.connected);
  const primaryLabel = creating
    ? "Đang tạo…"
    : busy
      ? "Đang tạo link…"
      : "Kết nối YouTube";

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
      <div className="space-y-3 p-4 sm:px-5">
        {destinations.length === 0 ? (
          <div className="p-6 text-center">
            <p className="text-sm font-semibold text-slate-900">Chưa kết nối kênh YouTube</p>
            <p className="mt-1 text-xs text-slate-500">
              Kết nối kênh để video từ Facebook tự động đăng lên YouTube.
            </p>
            <button
              type="button"
              className={`${btnSmall} mt-3`}
              disabled={creating || busy !== null}
              onClick={handlePrimaryConnect}
            >
              <IconPlus size={14} className="mr-1" />
              {primaryLabel}
            </button>
            {showAdvanced ? (
              <div className="mx-auto mt-4 max-w-sm space-y-3 rounded-2xl border border-slate-200/90 bg-white p-4 text-left">
                <div>
                  <label className={labelCls}>Visibility</label>
                  <select value={newDestVisibility} onChange={(e) => setNewDestVisibility(e.target.value)} className={inputCls}>
                    <option value="public">Public (công khai)</option>
                    <option value="unlisted">Unlisted (có link mới xem được)</option>
                    <option value="private">Private (chỉ mình bạn)</option>
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
              </div>
            ) : null}
            <div className="mt-2">
              <button
                type="button"
                className="text-xs text-slate-400 underline underline-offset-2 hover:text-slate-600"
                onClick={() => setShowAdvanced((v) => !v)}
              >
                {showAdvanced ? "Ẩn tùy chọn" : "Tùy chọn nâng cao"}
              </button>
            </div>
          </div>
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
            {pendingDestination ? (
              <button
                type="button"
                className={btnSmall}
                disabled={creating || busy !== null}
                onClick={() => connect(pendingDestination.id)}
              >
                <IconPlus size={14} className="mr-1" />
                {busy === pendingDestination.id ? "Đang tạo link…" : "Kết nối YouTube"}
              </button>
            ) : null}
          </div>
        )}
      </div>
    </Card>
  );
}
