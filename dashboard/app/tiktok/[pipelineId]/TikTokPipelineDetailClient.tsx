"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Badge, Card, CardHeader, Spinner, btnPrimary, btnSecondary, btnSmall, inputCls, labelCls } from "@/components/ui";
import { IconAlert, IconCheck, IconClock, IconFilm, IconPlay, IconPlus, IconRefresh, IconTikTok, IconUpload, IconVideo } from "@/components/icons";
import { TikTokPipelineToggles } from "@/components/tiktok/TikTokPipelineToggles";
import { TikTokOverview } from "@/components/tiktok/TikTokOverview";
import { TikTokAiSettings } from "@/components/tiktok/TikTokAiSettings";
import type {
  TikTokAiSettingsDto,
  TikTokDestinationDto,
  TikTokFlowState,
  TikTokPipelineDto,
  TikTokReelDto,
  TikTokScheduleDto,
  TikTokSlotDto,
  TikTokSourceDto,
  TikTokSummaryDto,
} from "@/lib/tiktok-api";

function formatDuration(sec: number | null): string {
  if (sec === null || sec === undefined || Number.isNaN(sec)) return "—";
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function TikTokPipelineDetailClient({
  pipeline,
  summary,
  initialSources = [],
  destinations = [],
  initialSchedule = null,
  initialSlots = [],
  initialFlow = null,
  initialAiSettings = null,
  channelAvatarUrl = null,
  channelName = null,
}: {
  pipeline: TikTokPipelineDto;
  summary: TikTokSummaryDto | null;
  initialSources: TikTokSourceDto[];
  destinations: TikTokDestinationDto[];
  initialSchedule: TikTokScheduleDto | null;
  initialSlots: TikTokSlotDto[];
  initialFlow?: TikTokFlowState | null;
  initialAiSettings?: TikTokAiSettingsDto | null;
  channelAvatarUrl?: string | null;
  channelName?: string | null;
}) {
  const router = useRouter();
  const [tab, setTab] = useState<"overview" | "sources" | "inventory" | "schedule" | "destinations" | "ai-settings">("overview");

  // Sources
  const [sources, setSources] = useState<TikTokSourceDto[]>(initialSources);
  const [showAddSource, setShowAddSource] = useState(false);
  const [newUsername, setNewUsername] = useState("");
  const [newDisplayName, setNewDisplayName] = useState("");
  const [addingSource, setAddingSource] = useState(false);
  const [addSourceError, setAddSourceError] = useState<string | null>(null);

  // Scan
  const [scanningSourceId, setScanningSourceId] = useState<string | null>(null);
  const [scanMessage, setScanMessage] = useState<string | null>(null);

  // Inventory
  const [selectedSourceId, setSelectedSourceId] = useState<string>(initialSources[0]?.id || "");
  const [inventory, setInventory] = useState<TikTokReelDto[]>([]);
  const [loadingInventory, setLoadingInventory] = useState(false);

  // Schedule
  const [schedule, setSchedule] = useState<TikTokScheduleDto | null>(initialSchedule);
  const [slots, setSlots] = useState<TikTokSlotDto[]>(initialSlots);
  const [generatingSlots, setGeneratingSlots] = useState(false);

  // Add source handler
  async function handleAddSource(e: React.FormEvent) {
    e.preventDefault();
    const cleanUser = newUsername.trim();
    if (!cleanUser || addingSource) return;

    setAddingSource(true);
    setAddSourceError(null);

    try {
      const res = await fetch("/api/tiktok/sources", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pipeline_id: pipeline.id,
          username: cleanUser,
          display_name: newDisplayName.trim() || undefined,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || data.message || "Không thể thêm nguồn TikTok.");
      }
      setSources((prev) => {
        if (prev.some((s) => s.id === data.id)) return prev;
        return [data, ...prev];
      });
      setShowAddSource(false);
      setNewUsername("");
      setNewDisplayName("");
      if (!selectedSourceId) setSelectedSourceId(data.id);
      router.refresh();
    } catch (err) {
      setAddSourceError(err instanceof Error ? err.message : "Thêm nguồn thất bại.");
    } finally {
      setAddingSource(false);
    }
  }

  // Scan source handler
  async function handleScan(sourceId: string) {
    if (scanningSourceId) return;
    setScanningSourceId(sourceId);
    setScanMessage(null);

    try {
      const res = await fetch(`/api/tiktok/sources/${encodeURIComponent(sourceId)}/scan`, {
        method: "POST",
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || data.message || "Không thể quét nguồn.");
      }
      setScanMessage("Đã kích hoạt quét video TikTok thành công! Quá trình đang chạy nền.");
      setTimeout(() => setScanMessage(null), 5000);
      router.refresh();
    } catch (err) {
      setScanMessage(err instanceof Error ? err.message : "Quét thất bại.");
    } finally {
      setScanningSourceId(null);
    }
  }

  // Load inventory for selected source
  async function loadInventory(sourceId: string) {
    if (!sourceId) return;
    setLoadingInventory(true);
    try {
      const res = await fetch(`/api/tiktok/inventory?source_id=${encodeURIComponent(sourceId)}`);
      if (res.ok) {
        const data = await res.json();
        setInventory(Array.isArray(data) ? data : []);
      }
    } catch {
      // ignore
    } finally {
      setLoadingInventory(false);
    }
  }

  // Trigger inventory load when switching to inventory tab
  function handleSelectInventoryTab(sourceId?: string) {
    setTab("inventory");
    const target = sourceId || selectedSourceId || sources[0]?.id;
    if (target) {
      setSelectedSourceId(target);
      void loadInventory(target);
    }
  }

  // Generate Schedule Slots handler
  async function handleGenerateSlots() {
    if (generatingSlots) return;
    setGeneratingSlots(true);
    try {
      const res = await fetch("/api/tiktok/schedule", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pipeline_id: pipeline.id,
          action: "generate_slots",
        }),
      });
      if (res.ok) {
        // reload slots
        const reloadRes = await fetch(`/api/tiktok/schedule?pipeline_id=${encodeURIComponent(pipeline.id)}`);
        if (reloadRes.ok) {
          const data = await reloadRes.json();
          setSlots(data.slots || []);
        }
      }
    } catch {
      // ignore
    } finally {
      setGeneratingSlots(false);
    }
  }

  return (
    <div className="w-full min-w-0 space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <Link href="/tiktok" className="text-xs font-semibold text-slate-500 hover:text-slate-700">
              TikTok Pipelines
            </Link>
            <span className="text-slate-300">/</span>
            <span className="text-xs font-semibold text-slate-700">{pipeline.name}</span>
          </div>
          <h1 className="mt-1 text-2xl font-extrabold text-slate-900">{pipeline.name}</h1>
          <p className="text-xs text-slate-500">Slug: @{pipeline.slug}</p>
        </div>

        <div className="flex items-center gap-3">
          <Link
            href="/tiktok/manual"
            className="inline-flex min-h-[44px] items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50"
          >
            Manual Publish
          </Link>
          <TikTokPipelineToggles
            pipelineId={pipeline.id}
            initialEnabled={pipeline.enabled}
            initialAutoPublish={pipeline.auto_publish}
          />
        </div>
      </div>

      {/* Tabs */}
      <div className="flex flex-wrap gap-2 border-b border-slate-200 pb-3">
        {[
          { key: "overview", label: "Tổng quan" },
          { key: "sources", label: `Nguồn video (${sources.length})` },
          { key: "inventory", label: "Kho video (Inventory)" },
          { key: "schedule", label: "Lịch đăng (Schedule)" },
          { key: "destinations", label: `Kênh đích (${destinations.length})` },
          { key: "ai-settings", label: "Cấu hình AI" },
        ].map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => {
              if (t.key === "inventory") handleSelectInventoryTab();
              else setTab(t.key as any);
            }}
            className={`rounded-xl px-4 py-2 text-xs font-bold transition ${
              tab === t.key
                ? "bg-indigo-600 text-white shadow-sm"
                : "bg-white text-slate-700 border border-slate-200 hover:bg-slate-50"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Scan notification message */}
      {scanMessage && (
        <div className="flex items-center gap-2 rounded-xl bg-indigo-50 p-3 text-sm text-indigo-700 border border-indigo-200">
          <IconCheck size={16} />
          <span>{scanMessage}</span>
        </div>
      )}

      {/* Tab: Overview */}
      {tab === "overview" && (
        <div className="space-y-6">
          <TikTokOverview
            pipeline={pipeline}
            initialFlow={initialFlow}
            channelAvatarUrl={channelAvatarUrl}
            channelName={channelName}
          />

          <div className="grid gap-6 md:grid-cols-2">
            <Card>
              <CardHeader
                title="Kênh YouTube nhận video"
                subtitle="Destinations liên kết"
                icon={<IconUpload size={18} />}
              />
              <div className="p-4 sm:p-5">
                {destinations.length === 0 ? (
                  <p className="text-xs text-slate-500">Chưa có kênh YouTube nào được kết nối.</p>
                ) : (
                  <div className="space-y-2">
                    {destinations.map((d) => (
                      <div key={d.id} className="flex items-center justify-between rounded-xl bg-slate-50 p-3">
                        <div>
                          <p className="font-bold text-slate-900 text-sm">{d.channel_name || "YouTube"}</p>
                          <p className="text-[11px] text-slate-400">ID: {d.channel_id || d.id}</p>
                        </div>
                        {d.connected ? <Badge tone="green" dot>Đã liên kết</Badge> : <Badge tone="amber">Chưa OAuth</Badge>}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </Card>

            <Card>
              <CardHeader
                title="Nguồn TikTok (Top Creators)"
                subtitle={`${sources.length} tài khoản đang theo dõi`}
                icon={<IconTikTok size={18} />}
                action={
                  <button type="button" onClick={() => setShowAddSource(true)} className={btnSmall}>
                    + Thêm nguồn
                  </button>
                }
              />
              <div className="p-4 sm:p-5">
                {sources.length === 0 ? (
                  <p className="text-xs text-slate-500">Chưa có nguồn TikTok nào. Bấm nút Thêm nguồn để bắt đầu.</p>
                ) : (
                  <div className="space-y-2">
                    {sources.slice(0, 4).map((s) => (
                      <div key={s.id} className="flex items-center justify-between rounded-xl bg-slate-50 p-3">
                        <div>
                          <p className="font-bold text-slate-900 text-sm">@{s.username}</p>
                          <p className="text-[11px] text-slate-400">{s.discovered_total || 0} video tìm thấy</p>
                        </div>
                        <button
                          type="button"
                          onClick={() => handleScan(s.id)}
                          disabled={scanningSourceId === s.id}
                          className={btnSmall}
                        >
                          {scanningSourceId === s.id ? <Spinner size={12} /> : "Quét"}
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </Card>
          </div>
        </div>
      )}

      {/* Tab: Sources */}
      {tab === "sources" && (
        <Card>
          <CardHeader
            title="Quản lý Nguồn TikTok (Sources)"
            subtitle="Các tài khoản creator TikTok để hệ thống tự động quét video"
            icon={<IconTikTok size={18} />}
            action={
              <button type="button" onClick={() => setShowAddSource(true)} className={btnPrimary}>
                + Thêm nguồn TikTok
              </button>
            }
          />
          <div className="overflow-x-auto">
            {sources.length === 0 ? (
              <div className="p-8 text-center text-sm text-slate-500">
                Chưa có tài khoản TikTok nào trong pipeline này.
              </div>
            ) : (
              <table className="w-full text-left text-sm text-slate-700">
                <thead className="border-b border-slate-100 bg-slate-50 text-xs uppercase text-slate-500">
                  <tr>
                    <th className="px-4 py-3">Creator / Username</th>
                    <th className="px-4 py-3">Trạng thái</th>
                    <th className="px-4 py-3">Video tìm thấy</th>
                    <th className="px-4 py-3">Lần quét gần nhất</th>
                    <th className="px-4 py-3 text-right">Thao tác</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {sources.map((s) => (
                    <tr key={s.id} className="hover:bg-slate-50/50">
                      <td className="px-4 py-3">
                        <p className="font-bold text-slate-900">@{s.username}</p>
                        {s.display_name && <p className="text-xs text-slate-500">{s.display_name}</p>}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap items-center gap-1.5">
                          {s.enabled ? <Badge tone="green" dot>Bật</Badge> : <Badge tone="slate">Tắt</Badge>}
                          {s.last_scan_status === "failed" ? (
                            <Badge tone="rose">Lỗi quét</Badge>
                          ) : s.last_scan_status === "running" ? (
                            <Badge tone="indigo" dot>Đang quét...</Badge>
                          ) : null}
                        </div>
                        {s.last_scan_error && s.last_scan_status === "failed" && (
                          <p className="mt-1 max-w-[240px] truncate text-[11px] text-rose-600" title={s.last_scan_error}>
                            {s.last_scan_error}
                          </p>
                        )}
                      </td>
                      <td className="px-4 py-3 font-semibold text-slate-900">
                        {s.discovered_total || 0}
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-500">
                        {s.last_scan_at ? new Date(s.last_scan_at).toLocaleString("vi-VN") : "Chưa quét"}
                      </td>
                      <td className="px-4 py-3 text-right space-x-2">
                        <button
                          type="button"
                          onClick={() => handleSelectInventoryTab(s.id)}
                          className={btnSmall}
                        >
                          Xem video
                        </button>
                        <button
                          type="button"
                          onClick={() => handleScan(s.id)}
                          disabled={scanningSourceId === s.id}
                          className={`${btnSmall} bg-indigo-50 text-indigo-700 border-indigo-200 hover:bg-indigo-100`}
                        >
                          {scanningSourceId === s.id ? <Spinner size={12} /> : "Quét ngay"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </Card>
      )}

      {/* Tab: Inventory */}
      {tab === "inventory" && (
        <Card>
          <CardHeader
            title="Kho video TikTok (Inventory)"
            subtitle="Danh sách các video đã được quét và lưu trữ"
            icon={<IconFilm size={18} />}
            action={
              <div className="flex items-center gap-2">
                <select
                  value={selectedSourceId}
                  onChange={(e) => {
                    setSelectedSourceId(e.target.value);
                    void loadInventory(e.target.value);
                  }}
                  className={`${inputCls} text-xs py-1.5`}
                >
                  {sources.map((s) => (
                    <option key={s.id} value={s.id}>
                      @{s.username}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={() => void loadInventory(selectedSourceId)}
                  className={btnSmall}
                  disabled={loadingInventory}
                >
                  <IconRefresh size={14} />
                </button>
              </div>
            }
          />
          <div className="overflow-x-auto">
            {loadingInventory ? (
              <div className="p-8 text-center text-sm text-slate-500">
                <Spinner /> Đang tải kho video…
              </div>
            ) : inventory.length === 0 ? (
              <div className="p-8 text-center text-sm text-slate-500">
                Nguồn này chưa có video nào trong kho. Hãy bấm &quot;Quét ngay&quot; ở tab Nguồn video.
              </div>
            ) : (
              <table className="w-full text-left text-sm text-slate-700">
                <thead className="border-b border-slate-100 bg-slate-50 text-xs uppercase text-slate-500">
                  <tr>
                    <th className="px-4 py-3">Video</th>
                    <th className="px-4 py-3">Tiêu đề / Caption</th>
                    <th className="px-4 py-3">Thời lượng</th>
                    <th className="px-4 py-3">Lượt xem</th>
                    <th className="px-4 py-3">Trạng thái</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {inventory.map((reel) => (
                    <tr key={reel.id} className="hover:bg-slate-50/50">
                      <td className="px-4 py-3">
                        {reel.thumbnail_url ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img
                            src={reel.thumbnail_url}
                            alt=""
                            className="h-12 w-9 rounded object-cover shadow-sm"
                          />
                        ) : (
                          <div className="h-12 w-9 rounded bg-slate-100 flex items-center justify-center text-slate-400">
                            <IconVideo size={16} />
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3 max-w-sm">
                        <p className="font-semibold text-slate-900 truncate">
                          {reel.caption || "TikTok Video"}
                        </p>
                        <p className="text-[11px] text-slate-400">ID: {reel.reel_id}</p>
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-600">
                        {formatDuration(reel.duration)}
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-600">
                        {reel.play_count ? Number(reel.play_count).toLocaleString() : "—"}
                      </td>
                      <td className="px-4 py-3">
                        {reel.status === "published" ? (
                          <Badge tone="green" dot>Đã đăng</Badge>
                        ) : reel.status === "queued" ? (
                          <Badge tone="amber" dot>Chờ đăng</Badge>
                        ) : (
                          <Badge tone="slate">Trong kho</Badge>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </Card>
      )}

      {/* Tab: Schedule */}
      {tab === "schedule" && (
        <div className="space-y-6">
          <Card>
            <CardHeader
              title="Cấu hình lịch tự động đăng"
              subtitle="Thời gian batch đăng và số lượng video tối đa mỗi ngày"
              icon={<IconClock size={18} />}
            />
            <div className="p-4 sm:p-5 space-y-4">
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                  <span className="text-xs text-slate-500">Giờ quét lô (Batch time)</span>
                  <p className="mt-1 text-lg font-bold text-slate-900">{schedule?.batch_time || "06:00"}</p>
                </div>
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                  <span className="text-xs text-slate-500">Múi giờ</span>
                  <p className="mt-1 text-lg font-bold text-slate-900">{schedule?.timezone || "Asia/Ho_Chi_Minh"}</p>
                </div>
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                  <span className="text-xs text-slate-500">Tối đa mỗi ngày</span>
                  <p className="mt-1 text-lg font-bold text-slate-900">{schedule?.max_daily || 5} video</p>
                </div>
              </div>
            </div>
          </Card>

          <Card>
            <CardHeader
              title="Khung giờ đăng đã xếp hàng (Schedule Slots)"
              subtitle={`${slots.length} khung giờ đã lên lịch`}
              icon={<IconPlay size={18} />}
              action={
                <button
                  type="button"
                  onClick={handleGenerateSlots}
                  disabled={generatingSlots}
                  className={btnPrimary}
                >
                  {generatingSlots ? <Spinner size={14} /> : "Tạo khung giờ mới"}
                </button>
              }
            />
            <div className="overflow-x-auto">
              {slots.length === 0 ? (
                <div className="p-8 text-center text-sm text-slate-500">
                  Chưa có khung giờ đăng nào. Bấm &quot;Tạo khung giờ mới&quot; để xếp lịch.
                </div>
              ) : (
                <table className="w-full text-left text-sm text-slate-700">
                  <thead className="border-b border-slate-100 bg-slate-50 text-xs uppercase text-slate-500">
                    <tr>
                      <th className="px-4 py-3">Thời gian đăng</th>
                      <th className="px-4 py-3">Trạng thái</th>
                      <th className="px-4 py-3">Video gắn kèm</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {slots.map((slot) => (
                      <tr key={slot.id} className="hover:bg-slate-50/50">
                        <td className="px-4 py-3 font-semibold text-slate-900">
                          {new Date(slot.slot_time).toLocaleString("vi-VN")}
                        </td>
                        <td className="px-4 py-3">
                          {slot.status === "completed" ? (
                            <Badge tone="green" dot>Hoàn tất</Badge>
                          ) : slot.status === "assigned" ? (
                            <Badge tone="indigo" dot>Đã gán video</Badge>
                          ) : (
                            <Badge tone="slate">Khung trống</Badge>
                          )}
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-500">
                          {slot.reel_id ? `Reel #${slot.reel_id}` : "Chưa có"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </Card>
        </div>
      )}

      {/* Tab: Destinations */}
      {tab === "destinations" && (
        <Card>
          <CardHeader
            title="Kênh YouTube đích (Destinations)"
            subtitle="Danh sách các kênh nhận video xuất bản từ pipeline này"
            icon={<IconUpload size={18} />}
            action={
              <Link href="/tiktok/manual" className={btnPrimary}>
                Quản lý &amp; Thêm kênh
              </Link>
            }
          />
          <div className="p-4 sm:p-5">
            {destinations.length === 0 ? (
              <div className="p-8 text-center text-sm text-slate-500">
                Chưa có kênh YouTube nào được cấu hình cho pipeline này.
              </div>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2">
                {destinations.map((d) => (
                  <div key={d.id} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
                    <div className="flex items-center justify-between">
                      <p className="font-bold text-slate-900">{d.channel_name || "YouTube Channel"}</p>
                      {d.connected ? <Badge tone="green" dot>Đã liên kết</Badge> : <Badge tone="amber">Chưa OAuth</Badge>}
                    </div>
                    <p className="mt-1 text-xs text-slate-500">Kênh ID: {d.channel_id || d.id}</p>
                    <p className="text-[11px] text-slate-400">Chế độ mặc định: {d.visibility}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </Card>
      )}

      {/* Tab: AI Settings */}
      {tab === "ai-settings" && (
        <TikTokAiSettings
          pipelineId={pipeline.id}
          initialSettings={initialAiSettings ?? null}
        />
      )}

      {/* Add Source Modal */}
      {showAddSource && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
          <div className="w-full max-w-md rounded-3xl border border-slate-200 bg-white p-6 shadow-2xl">
            <h3 className="text-lg font-extrabold text-slate-900">Thêm tài khoản TikTok nguồn</h3>
            {addSourceError && (
              <div className="mt-3 rounded-lg bg-rose-50 p-3 text-sm text-rose-600 border border-rose-200">
                {addSourceError}
              </div>
            )}
            <form onSubmit={handleAddSource} className="mt-4 space-y-4">
              <div>
                <label className={labelCls}>TikTok Username hoặc Link Profile</label>
                <input
                  type="text"
                  value={newUsername}
                  onChange={(e) => setNewUsername(e.target.value)}
                  className={inputCls}
                  placeholder="@citrachoighelam_19 hoặc link TikTok"
                  required
                  disabled={addingSource}
                />
                <p className="mt-1.5 text-[11px] text-slate-400">
                  Hỗ trợ: @username, username, link tiktok.com/@username hoặc link rút gọn vt.tiktok.com
                </p>
              </div>
              <div>
                <label className={labelCls}>Tên gợi nhớ (Tùy chọn)</label>
                <input
                  type="text"
                  value={newDisplayName}
                  onChange={(e) => setNewDisplayName(e.target.value)}
                  className={inputCls}
                  placeholder="Citra 🐈"
                  disabled={addingSource}
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowAddSource(false)}
                  className={btnSecondary}
                  disabled={addingSource}
                >
                  Hủy
                </button>
                <button type="submit" className={btnPrimary} disabled={addingSource}>
                  {addingSource ? "Đang thêm…" : "Thêm nguồn"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
