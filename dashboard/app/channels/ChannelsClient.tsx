"use client";

import { useState, useTransition } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Badge, Card, EmptyState, PageHeader } from "@/components/ui";
import { IconAlert, IconChannels, IconPlus, IconRefresh, IconX } from "@/components/icons";
import type { ChannelItem, Pipeline } from "@/lib/types";
import { actionCreateDestination, actionGetOauthUrl } from "@/lib/actions";

interface ChannelsClientProps {
  initialChannels: ChannelItem[];
  pipelines: Pipeline[];
}

export function ChannelsClient({ initialChannels, pipelines }: ChannelsClientProps) {
  const router = useRouter();
  const [channels, setChannels] = useState<ChannelItem[]>(initialChannels);
  const [loading, setLoading] = useState(false);
  const [showConnectModal, setShowConnectModal] = useState(false);
  const [connectName, setConnectName] = useState("");
  const [selectedPipelineId, setSelectedPipelineId] = useState(
    pipelines[0]?.id || "",
  );
  const [connectError, setConnectError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const handleRefresh = async () => {
    try {
      setLoading(true);
      const res = await fetch("/api/channels");
      if (res.ok) {
        const data: ChannelItem[] = await res.json();
        setChannels(data);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const handleStartConnect = () => {
    setConnectError(null);
    if (!selectedPipelineId && pipelines.length > 0) {
      setSelectedPipelineId(pipelines[0].id);
    }
    setShowConnectModal(true);
  };

  const handleSubmitConnect = () => {
    if (!selectedPipelineId) {
      setConnectError("Vui lòng chọn pipeline để liên kết với YouTube channel.");
      return;
    }
    const name = connectName.trim() || "YouTube Channel";

    startTransition(async () => {
      try {
        const form = new FormData();
        form.set("name", name);
        form.set("platform", "youtube");
        form.set("pipeline_id", selectedPipelineId);

        const createRes = await actionCreateDestination(selectedPipelineId, form);
        if (!createRes.ok) {
          setConnectError(createRes.error || "Không thể tạo destination");
          return;
        }

        const oauthUrl = createRes.oauthUrl;
        if (oauthUrl) {
          window.location.assign(oauthUrl);
          return;
        }

        const oauthRes = await actionGetOauthUrl(createRes.id);
        if (!oauthRes.ok) {
          setConnectError(oauthRes.error || "Không lấy được YouTube OAuth URL");
          return;
        }
        if (oauthRes.url) {
          window.location.assign(oauthRes.url);
        }
      } catch (err: unknown) {
        setConnectError(err instanceof Error ? err.message : "Thao tác kết nối thất bại");
      }
    });
  };

  const handleQuickOAuth = (destinationId: string) => {
    startTransition(async () => {
      const oauthRes = await actionGetOauthUrl(destinationId);
      if (!oauthRes.ok) {
        alert(oauthRes.error || "Không lấy được link kết nối Google");
        return;
      }
      if (oauthRes.url) {
        window.location.assign(oauthRes.url);
      }
    });
  };

  return (
    <>
      <PageHeader
        eyebrow="Publishing Targets"
        title="Channels"
        description="Manage your connected publishing channels."
        actions={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleRefresh}
              disabled={loading}
              className="inline-flex min-h-[44px] items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50"
            >
              <IconRefresh size={14} />
              {loading ? "Đang tải…" : "Làm mới"}
            </button>
            <button
              type="button"
              onClick={handleStartConnect}
              className="inline-flex min-h-[44px] items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2 text-xs font-bold text-white shadow-[0_4px_12px_-4px_rgba(79,70,229,0.5)] transition hover:bg-indigo-500"
            >
              <IconPlus size={15} />
              + Connect YouTube
            </button>
          </div>
        }
      />

      <div className="mt-6">
        {channels.length === 0 ? (
          <Card className="p-8 sm:p-12 text-center">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-indigo-50 text-indigo-600">
              <IconChannels size={28} />
            </div>
            <h3 className="mt-4 text-base font-extrabold text-slate-900">
              No YouTube channels connected yet.
            </h3>
            <p className="mt-1.5 text-xs text-slate-500 max-w-sm mx-auto">
              Kết nối kênh YouTube đầu tiên của bạn để bắt đầu đăng video tự động hoặc thủ công từ Douyin.
            </p>
            <div className="mt-6">
              <button
                type="button"
                onClick={handleStartConnect}
                className="inline-flex min-h-[44px] items-center gap-2 rounded-xl bg-indigo-600 px-6 py-2.5 text-sm font-bold text-white shadow-md transition hover:bg-indigo-500"
              >
                <IconPlus size={16} />
                + Connect YouTube
              </button>
            </div>
          </Card>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {channels.map((ch) => {
              const isConnected = ch.connected;
              return (
                <div
                  key={ch.id}
                  className="group relative flex flex-col justify-between rounded-2xl border border-slate-200/90 bg-white p-5 shadow-sm transition hover:border-indigo-300 hover:shadow-md"
                >
                  <div>
                    {/* Header: Avatar & Title */}
                    <div className="flex items-start gap-3.5">
                      <div className="relative h-12 w-12 shrink-0 overflow-hidden rounded-2xl bg-slate-900 ring-1 ring-slate-900/10">
                        {ch.avatar_url ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img
                            src={ch.avatar_url}
                            alt={ch.channel_title}
                            className="h-full w-full object-cover"
                          />
                        ) : (
                          <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-rose-500 to-red-600 font-extrabold text-white text-base">
                            {(ch.channel_title || "Y")[0].toUpperCase()}
                          </div>
                        )}
                        <span className="absolute bottom-0 right-0 flex h-4 w-4 items-center justify-center rounded-tl-md bg-red-600 text-[8px] font-black text-white">
                          YT
                        </span>
                      </div>

                      <div className="min-w-0 flex-1">
                        <Link
                          href={`/channels/${ch.destination_id}`}
                          className="block truncate text-base font-extrabold text-slate-900 group-hover:text-indigo-600 transition"
                        >
                          {ch.channel_title}
                        </Link>
                        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs">
                          <span className="inline-flex items-center rounded-md bg-red-50 px-1.5 py-0.5 font-bold text-red-700 text-[10px]">
                            YouTube
                          </span>
                          {isConnected ? (
                            <Badge tone="green" dot>Connected</Badge>
                          ) : (
                            <Badge tone="slate" dot>Not Connected</Badge>
                          )}
                          {ch.enabled ? (
                            <Badge tone="green">Auto ON</Badge>
                          ) : (
                            <Badge tone="amber">Auto OFF</Badge>
                          )}
                        </div>
                      </div>
                    </div>

                    {/* Pipeline Info */}
                    <div className="mt-4 rounded-xl bg-slate-50 p-3 text-xs">
                      <p className="text-slate-400 font-medium">Workspace Pipeline:</p>
                      <p className="mt-0.5 font-bold text-slate-800 truncate">
                        {ch.pipeline_name}
                      </p>
                    </div>

                    {/* Stats Grid */}
                    <div className="mt-3 grid grid-cols-2 gap-2 border-t border-slate-100 pt-3 text-xs">
                      <div className="rounded-xl border border-slate-100 bg-white p-2.5">
                        <p className="text-[11px] font-medium text-slate-400">Published today</p>
                        <p className="mt-1 text-lg font-black text-slate-900">
                          {ch.published_today}
                        </p>
                      </div>
                      <div className="rounded-xl border border-slate-100 bg-white p-2.5">
                        <p className="text-[11px] font-medium text-slate-400">Queue</p>
                        <p className="mt-1 text-lg font-black text-slate-900">
                          {ch.queue_count}
                        </p>
                      </div>
                    </div>
                  </div>

                  {/* Actions footer */}
                  <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3.5">
                    {isConnected ? (
                      <Link
                        href={`/channels/${ch.destination_id}`}
                        className="inline-flex min-h-[44px] w-full items-center justify-center gap-1.5 rounded-xl bg-indigo-50 px-4 py-2 text-xs font-bold text-indigo-700 transition hover:bg-indigo-100"
                      >
                        Open Workspace →
                      </Link>
                    ) : (
                      <div className="flex w-full items-center gap-2">
                        <button
                          type="button"
                          onClick={() => handleQuickOAuth(ch.destination_id)}
                          disabled={pending}
                          className="inline-flex min-h-[44px] flex-1 items-center justify-center rounded-xl bg-amber-500 px-3 py-2 text-xs font-bold text-white shadow-sm hover:bg-amber-600 disabled:opacity-50"
                        >
                          {pending ? "Đang mở OAuth…" : "Connect OAuth"}
                        </button>
                        <Link
                          href={`/channels/${ch.destination_id}`}
                          className="inline-flex min-h-[44px] items-center justify-center rounded-xl border border-slate-200 px-3 py-2 text-xs font-bold text-slate-600 hover:bg-slate-50"
                        >
                          Chi tiết
                        </Link>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Connect Modal */}
      {showConnectModal ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-sm font-extrabold text-slate-900 flex items-center gap-2">
                <IconChannels size={18} />
                Connect YouTube Channel
              </h3>
              <button
                type="button"
                onClick={() => setShowConnectModal(false)}
                className="rounded-lg p-1 text-slate-400 hover:text-slate-600"
              >
                <IconX size={16} />
              </button>
            </div>

            <div className="mt-4 space-y-4">
              <p className="text-xs text-slate-500">
                Tạo một Publishing Channel mới và đăng nhập Google OAuth để cấp quyền upload video lên YouTube.
              </p>

              <div>
                <label className="text-xs font-bold text-slate-700">Tên Channel / Nhãn hiển thị</label>
                <input
                  type="text"
                  value={connectName}
                  onChange={(e) => setConnectName(e.target.value)}
                  placeholder="Ví dụ: Vibe Men World Shorts"
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm font-semibold text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none"
                />
              </div>

              <div>
                <label className="text-xs font-bold text-slate-700">Liên kết với Pipeline</label>
                {pipelines.length === 0 ? (
                  <p className="mt-1 text-xs text-rose-600">
                    Chưa có pipeline nào. Vui lòng tạo một pipeline trước.
                  </p>
                ) : (
                  <select
                    value={selectedPipelineId}
                    onChange={(e) => setSelectedPipelineId(e.target.value)}
                    className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm font-semibold text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none"
                  >
                    {pipelines.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name} ({p.slug})
                      </option>
                    ))}
                  </select>
                )}
              </div>

              {connectError ? (
                <p className="flex items-center gap-1.5 rounded-xl border border-rose-200 bg-rose-50 p-2.5 text-xs font-semibold text-rose-700">
                  <IconAlert size={14} />
                  {connectError}
                </p>
              ) : null}

              <div className="mt-6 flex items-center justify-end gap-2 border-t border-slate-100 pt-4">
                <button
                  type="button"
                  onClick={() => setShowConnectModal(false)}
                  className="inline-flex min-h-[44px] items-center rounded-xl border border-slate-200 px-4 py-2 text-xs font-bold text-slate-600 hover:bg-slate-50"
                >
                  Hủy
                </button>
                <button
                  type="button"
                  onClick={handleSubmitConnect}
                  disabled={pending || pipelines.length === 0}
                  className="inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-xl bg-indigo-600 px-5 py-2 text-xs font-bold text-white shadow-md hover:bg-indigo-500 disabled:opacity-50"
                >
                  {pending ? (
                    <>
                      <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                      Đang xử lý…
                    </>
                  ) : (
                    "Tiếp tục đăng nhập Google →"
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
