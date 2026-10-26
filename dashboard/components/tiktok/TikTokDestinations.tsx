"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Image from "next/image";
import {
  Card,
  CardHeader,
  Badge,
  Spinner,
  btnPrimary,
  btnSecondary,
  btnSmall,
  btnDanger,
} from "@/components/ui";
import {
  IconDestinations,
  IconPlus,
  IconRefresh,
  IconCheck,
  IconAlert,
  IconTrash,
} from "@/components/icons";
import type { TikTokDestinationDto } from "@/lib/tiktok-api";

export function TikTokDestinations({
  pipelineId,
  initial = [],
  onUpdate,
}: {
  pipelineId: string;
  initial?: TikTokDestinationDto[];
  onUpdate?: (dests: TikTokDestinationDto[]) => void;
}) {
  const searchParams = useSearchParams();
  const [destinations, setDestinations] = useState<TikTokDestinationDto[]>(initial);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [isStartingNew, setIsStartingNew] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [confirmDisconnect, setConfirmDisconnect] = useState<TikTokDestinationDto | null>(null);
  const [disconnecting, setDisconnecting] = useState(false);
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [settingDefaultId, setSettingDefaultId] = useState<string | null>(null);

  // Check URL query params for OAuth result
  useEffect(() => {
    if (searchParams.get("youtube_connected") === "1") {
      setSuccess("Đã liên kết kênh YouTube thành công!");
      refreshDestinations();
    }
    const err = searchParams.get("youtube_error");
    if (err) {
      setError(`Lỗi kết nối YouTube: ${decodeURIComponent(err)}`);
    }
  }, [searchParams]);

  async function refreshDestinations() {
    try {
      const res = await fetch(
        `/api/tiktok/pipelines/${encodeURIComponent(pipelineId)}/youtube-destinations`,
        { cache: "no-store" },
      );
      if (res.ok) {
        const list = (await res.json()) as TikTokDestinationDto[];
        if (Array.isArray(list)) {
          setDestinations(list);
          onUpdate?.(list);
        }
      }
    } catch {
      // ignore refresh errors
    }
  }

  async function startConnect(destinationId?: string) {
    if (destinationId) {
      setBusyId(destinationId);
    } else {
      setIsStartingNew(true);
    }
    setError(null);
    setSuccess(null);

    try {
      const returnTo = `/tiktok/${encodeURIComponent(pipelineId)}?tab=destinations`;
      const res = await fetch("/api/tiktok/oauth/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pipeline_id: pipelineId,
          destination_id: destinationId,
          return_to: returnTo,
        }),
      });

      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.authorization_url) {
        throw new Error(data.error || data.detail || "Không thể tạo liên kết đăng nhập Google OAuth.");
      }

      // Redirect user directly to Google OAuth consent
      window.location.href = data.authorization_url;
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Không thể bắt đầu kết nối YouTube.");
      setBusyId(null);
      setIsStartingNew(false);
    }
  }

  async function handleToggleEnabled(dest: TikTokDestinationDto) {
    setTogglingId(dest.id);
    setError(null);
    try {
      const nextEnabled = !dest.enabled;
      const res = await fetch(
        `/api/tiktok/youtube/destinations/${encodeURIComponent(dest.id)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ enabled: nextEnabled }),
        },
      );
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.error || "Không thể đổi trạng thái kênh.");
      }
      setDestinations((prev) => {
        const next = prev.map((item) =>
          item.id === dest.id ? { ...item, enabled: nextEnabled } : item,
        );
        onUpdate?.(next);
        return next;
      });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Lỗi khi cập nhật kênh.");
    } finally {
      setTogglingId(null);
    }
  }

  async function handleSetDefault(dest: TikTokDestinationDto) {
    setSettingDefaultId(dest.id);
    setError(null);
    try {
      const res = await fetch(
        `/api/tiktok/youtube/destinations/${encodeURIComponent(dest.id)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "default", pipeline_id: pipelineId }),
        },
      );
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.error || "Không thể đặt kênh mặc định.");
      }
      setDestinations((prev) => {
        const next = prev.map((item) => ({
          ...item,
          is_default: item.id === dest.id,
        }));
        onUpdate?.(next);
        return next;
      });
      setSuccess(`Đã đặt "${dest.channel_name || "YouTube"}" làm kênh mặc định.`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Lỗi khi đặt kênh mặc định.");
    } finally {
      setSettingDefaultId(null);
    }
  }

  async function handleDisconnect(dest: TikTokDestinationDto) {
    setDisconnecting(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/tiktok/youtube/destinations/${encodeURIComponent(dest.id)}`,
        { method: "DELETE" },
      );
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.error || "Không thể ngắt kết nối kênh.");
      }
      setDestinations((prev) => {
        const next = prev.map((item) =>
          item.id === dest.id ? { ...item, connected: false, is_default: false } : item,
        );
        onUpdate?.(next);
        return next;
      });
      setConfirmDisconnect(null);
      setSuccess(`Đã ngắt kết nối "${dest.channel_name || "YouTube"}".`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Lỗi khi ngắt kết nối.");
    } finally {
      setDisconnecting(false);
    }
  }

  return (
    <div className="space-y-4">
      {/* Alerts */}
      {success && (
        <div className="flex items-center justify-between rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          <div className="flex items-center gap-2">
            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-emerald-200 text-emerald-800">
              <IconCheck size={14} />
            </span>
            <span>{success}</span>
          </div>
          <button
            type="button"
            onClick={() => setSuccess(null)}
            className="text-xs font-semibold text-emerald-700 hover:text-emerald-900"
          >
            Đóng
          </button>
        </div>
      )}

      {error && (
        <div className="flex items-center justify-between rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
          <div className="flex items-center gap-2">
            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-rose-200 text-rose-800">
              <IconAlert size={14} />
            </span>
            <span>{error}</span>
          </div>
          <button
            type="button"
            onClick={() => setError(null)}
            className="text-xs font-semibold text-rose-700 hover:text-rose-900"
          >
            Đóng
          </button>
        </div>
      )}

      <Card>
        <CardHeader
          title={`Kênh YouTube đích (Destinations) (${destinations.length})`}
          subtitle="Quản lý các kênh YouTube nhận video xuất bản tự động hoặc thủ công"
          icon={<IconDestinations size={18} />}
          action={
            <button
              type="button"
              onClick={() => startConnect()}
              disabled={isStartingNew}
              className={`${btnPrimary} text-xs`}
            >
              {isStartingNew ? (
                <>
                  <Spinner size={14} /> Đang chuyển sang Google…
                </>
              ) : (
                <>
                  <IconPlus size={14} /> + Kết nối YouTube
                </>
              )}
            </button>
          }
        />

        <div className="p-4 sm:p-5">
          {destinations.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50/50 p-8 text-center sm:p-12">
              <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-indigo-50 text-indigo-600">
                <IconDestinations size={28} />
              </div>
              <h3 className="mt-3 text-base font-extrabold text-slate-900">
                Chưa có kênh YouTube nào được kết nối
              </h3>
              <p className="mx-auto mt-1.5 max-w-md text-xs leading-relaxed text-slate-500 sm:text-sm">
                Kết nối kênh YouTube để pipeline tự động đăng video theo lịch hoặc xem trước và xuất bản thủ công.
              </p>
              <div className="mt-5">
                <button
                  type="button"
                  onClick={() => startConnect()}
                  disabled={isStartingNew}
                  className={`${btnPrimary} min-h-[44px] px-6 text-sm`}
                >
                  {isStartingNew ? (
                    <>
                      <Spinner size={16} /> Đang mở Google OAuth…
                    </>
                  ) : (
                    <>
                      <IconPlus size={16} /> Kết nối kênh YouTube ngay
                    </>
                  )}
                </button>
              </div>
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-2">
              {destinations.map((d) => {
                const isBusy = busyId === d.id;
                const isToggling = togglingId === d.id;
                const isSettingDef = settingDefaultId === d.id;

                return (
                  <div
                    key={d.id}
                    className={`relative flex flex-col justify-between rounded-2xl border bg-white p-4 shadow-sm transition hover:shadow-md sm:p-5 ${
                      d.is_default
                        ? "border-indigo-300 ring-2 ring-indigo-50"
                        : "border-slate-200"
                    }`}
                  >
                    <div>
                      {/* Top row: Avatar + Channel Info + Badges */}
                      <div className="flex items-start gap-3.5">
                        {/* Channel Avatar */}
                        {d.channel_avatar_url ? (
                          <div className="relative h-12 w-12 shrink-0 overflow-hidden rounded-2xl border border-slate-200 bg-slate-100">
                            <Image
                              src={d.channel_avatar_url}
                              alt={d.channel_name || "YouTube"}
                              fill
                              sizes="48px"
                              className="object-cover"
                            />
                          </div>
                        ) : (
                          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 text-lg font-black text-white shadow-sm">
                            {(d.channel_name || "YT").slice(0, 1).toUpperCase()}
                          </div>
                        )}

                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <h4 className="truncate text-sm font-extrabold text-slate-900 sm:text-base">
                              {d.channel_name || "YouTube Channel"}
                            </h4>
                            {d.is_default && (
                              <Badge tone="indigo">Mặc định</Badge>
                            )}
                          </div>

                          <p className="mt-0.5 truncate font-mono text-[11px] text-slate-400">
                            ID: {d.channel_id || d.id}
                          </p>

                          <div className="mt-2 flex flex-wrap items-center gap-2">
                            {d.connected ? (
                              <Badge tone="green" dot>
                                Đã liên kết
                              </Badge>
                            ) : (
                              <Badge tone="amber" dot>
                                Chưa OAuth
                              </Badge>
                            )}

                            {d.enabled ? (
                              <Badge tone="slate">Đang kích hoạt</Badge>
                            ) : (
                              <Badge tone="red">Đang tắt</Badge>
                            )}
                          </div>
                        </div>
                      </div>

                      {/* Info snippet */}
                      <div className="mt-4 rounded-xl bg-slate-50 p-3 text-[11px] text-slate-600">
                        <div className="flex justify-between">
                          <span className="text-slate-400">Chế độ xuất bản:</span>
                          <span className="font-semibold capitalize text-slate-700">
                            {d.visibility}
                          </span>
                        </div>
                        {d.connected_at && (
                          <div className="mt-1 flex justify-between">
                            <span className="text-slate-400">Liên kết lúc:</span>
                            <span className="font-mono text-slate-700">
                              {new Date(d.connected_at).toLocaleDateString("vi-VN", {
                                year: "numeric",
                                month: "2-digit",
                                day: "2-digit",
                              })}
                            </span>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Action Bar */}
                    <div className="mt-5 border-t border-slate-100 pt-3.5">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        {/* Enable/Disable Toggle */}
                        <div className="flex items-center gap-2">
                          <button
                            type="button"
                            onClick={() => handleToggleEnabled(d)}
                            disabled={isToggling}
                            className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                              d.enabled ? "bg-indigo-600" : "bg-slate-200"
                            }`}
                            title={d.enabled ? "Tắt kênh này" : "Bật kênh này"}
                          >
                            <span
                              className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow-md ring-0 transition duration-200 ease-in-out ${
                                d.enabled ? "translate-x-5" : "translate-x-0"
                              }`}
                            />
                          </button>
                          <span className="text-xs font-semibold text-slate-600">
                            {d.enabled ? "Bật" : "Tắt"}
                          </span>
                        </div>

                        {/* Control buttons */}
                        <div className="flex flex-wrap items-center gap-1.5">
                          {!d.is_default && d.connected && (
                            <button
                              type="button"
                              onClick={() => handleSetDefault(d)}
                              disabled={isSettingDef}
                              className={`${btnSmall} text-xs`}
                              title="Chọn kênh này làm đích mặc định khi xuất bản"
                            >
                              {isSettingDef ? <Spinner size={12} /> : "Đặt mặc định"}
                            </button>
                          )}

                          <button
                            type="button"
                            onClick={() => startConnect(d.id)}
                            disabled={isBusy}
                            className={`${btnSmall} text-xs`}
                          >
                            {isBusy ? (
                              <>
                                <Spinner size={12} /> Đang mở…
                              </>
                            ) : d.connected ? (
                              <>
                                <IconRefresh size={12} /> Đổi kênh
                              </>
                            ) : (
                              <>
                                <IconPlus size={12} /> Cấp quyền OAuth
                              </>
                            )}
                          </button>

                          <button
                            type="button"
                            onClick={() => setConfirmDisconnect(d)}
                            className="inline-flex min-h-[32px] items-center justify-center rounded-lg border border-slate-200 px-2 text-slate-400 transition hover:border-rose-200 hover:bg-rose-50 hover:text-rose-600"
                            title="Ngắt kết nối kênh này"
                          >
                            <IconTrash size={14} />
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </Card>

      {/* Disconnect confirmation modal */}
      {confirmDisconnect && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-3xl border border-slate-200 bg-white p-6 shadow-2xl">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-rose-50 text-rose-600">
              <IconAlert size={24} />
            </div>

            <h3 className="mt-3 text-lg font-extrabold text-slate-900">
              Ngắt kết nối {confirmDisconnect.channel_name || "kênh YouTube"}?
            </h3>

            <p className="mt-2 text-xs leading-relaxed text-slate-500 sm:text-sm">
              Kênh sẽ chuyển sang trạng thái <b>Chưa cấp quyền OAuth</b>. Token và quyền truy cập YouTube của kênh này sẽ bị xoá khỏi hệ thống. Các video đã đăng trước đó trên YouTube vẫn được bảo lưu.
            </p>

            <div className="mt-6 flex justify-end gap-2.5">
              <button
                type="button"
                onClick={() => setConfirmDisconnect(null)}
                disabled={disconnecting}
                className={btnSecondary}
              >
                Huỷ
              </button>
              <button
                type="button"
                onClick={() => handleDisconnect(confirmDisconnect)}
                disabled={disconnecting}
                className={btnDanger}
              >
                {disconnecting ? (
                  <>
                    <Spinner size={14} /> Đang ngắt kết nối…
                  </>
                ) : (
                  "Ngắt kết nối ngay"
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
