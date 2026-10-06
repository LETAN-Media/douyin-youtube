"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Card, CardHeader, Badge, btnSmall, inputCls, labelCls } from "@/components/ui";

// Local shapes (same-origin fetch only — never import the server API client).
type Channel = {
  id: string;
  pipeline_id: string;
  pipeline_name: string | null;
  channel_id: string | null;
  channel_name: string | null;
  visibility: string;
  enabled: boolean;
  connected: boolean;
};

type Preview = {
  source_url: string;
  caption: string | null;
  thumbnail_url: string | null;
  duration: number | null;
  media_type: string;
};

type Pub = {
  id: string;
  channel_name: string | null;
  youtube_title: string | null;
  youtube_description: string | null;
  youtube_hashtags: string[];
  visibility: string;
  publish_at: string | null;
  status: string;
  stage: string | null;
  youtube_video_id: string | null;
  youtube_url: string | null;
  error_code: string | null;
  error: string | null;
  created_at: string | null;
  thumbnail_url?: string | null;
};

const STAGE_LABELS: Record<string, string> = {
  queued: "Đang chờ",
  claimed: "Đang chờ",
  processing: "Đang xử lý",
  resolving: "Đang lấy video Facebook",
  downloading: "Đang tải video",
  uploading: "Đang upload YouTube",
  completing: "Đang hoàn tất",
  completed: "Hoàn tất",
  failed: "Thất bại",
};

function stageLabel(status: string, stage: string | null): string {
  if (status === "published") return "Hoàn tất";
  if (status === "scheduled") return "Đã hẹn giờ";
  if (status === "failed") return "Thất bại";
  return STAGE_LABELS[stage ?? ""] ?? STAGE_LABELS[status] ?? status;
}

function formatDuration(sec: number | null): string {
  if (sec === null || sec === undefined || Number.isNaN(sec)) return "—";
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function initial(name: string | null): string {
  const c = (name ?? "?").trim().charAt(0).toUpperCase();
  return c || "?";
}

async function readError(res: Response): Promise<{ message: string; code: string | null; extra?: Record<string, unknown> }> {
  const data = (await res.json().catch(() => null)) as {
    error?: unknown;
    message?: unknown;
    existing_id?: unknown;
    existing_status?: unknown;
  } | null;
  const message =
    (typeof data?.error === "string" && data.error) ||
    (typeof data?.message === "string" && data.message) ||
    `HTTP ${res.status}`;
  return {
    message,
    code: typeof data?.error === "string" ? data.error : null,
    extra: data ?? undefined,
  };
}

type PipelineOption = {
  id: string;
  name: string;
};

type Destination = {
  id: string;
  connected?: boolean;
  channel_name?: string | null;
};

export function FacebookManualPublish({
  initialPipelines = [],
  justConnected = false,
}: {
  initialPipelines?: PipelineOption[];
  justConnected?: boolean;
}) {
  const router = useRouter();
  const [channels, setChannels] = useState<Channel[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Channel | null>(null);
  const [connectedToast, setConnectedToast] = useState(false);

  // Connect-YouTube flow state.
  const [pickerOpen, setPickerOpen] = useState(false);
  const [connecting, setConnecting] = useState<string | null>(null);
  const [connectError, setConnectError] = useState<string | null>(null);

  // Disconnect flow state.
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [disconnecting, setDisconnecting] = useState(false);
  const [disconnectError, setDisconnectError] = useState<string | null>(null);

  const duplicateCounts = useCallback(() => {
    const counts = new Map<string, number>();
    for (const ch of channels ?? []) {
      if (!ch.channel_id) continue;
      counts.set(ch.channel_id, (counts.get(ch.channel_id) ?? 0) + 1);
    }
    return counts;
  }, [channels]);

  async function handleDisconnect(destinationId: string) {
    if (disconnecting) return;
    setDisconnecting(true);
    setDisconnectError(null);
    try {
      const res = await fetch(
        `/api/facebook/manual/destinations/${encodeURIComponent(destinationId)}`,
        { method: "DELETE" },
      );
      if (!res.ok) {
        const e = await readError(res);
        if (res.status === 409) {
          throw new Error("Kênh đang có video chờ/đang upload. Hãy đợi hoàn tất rồi ngắt kết nối.");
        }
        throw new Error(e.message || "Không ngắt kết nối được.");
      }
      setChannels((prev) => (prev ?? []).filter((ch) => ch.id !== destinationId));
      if (selected?.id === destinationId) {
        setSelected(null);
        setPreview(null);
        setActive(null);
        setDuplicate(null);
        if (pollRef.current) clearInterval(pollRef.current);
      }
      setConfirmId(null);
      setMenuOpenId(null);
      void loadHistory(selected?.id === destinationId ? undefined : selected?.id);
    } catch (err) {
      setDisconnectError(err instanceof Error ? err.message : "Không ngắt kết nối được.");
    } finally {
      setDisconnecting(false);
    }
  }

  const [url, setUrl] = useState("");
  const [resolving, setResolving] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [resolveError, setResolveError] = useState<string | null>(null);

  const [aiOn, setAiOn] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [hashtags, setHashtags] = useState("");
  const [metaError, setMetaError] = useState<string | null>(null);

  const [mode, setMode] = useState<"now" | "private" | "scheduled">("now");
  const [schedDate, setSchedDate] = useState("");
  const [schedTime, setSchedTime] = useState("");
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);
  const [duplicate, setDuplicate] = useState<{ existing_id: string; existing_status: string } | null>(null);

  const [active, setActive] = useState<Pub | null>(null);
  const [history, setHistory] = useState<Pub[]>([]);
  const [historyTotal, setHistoryTotal] = useState(0);

  // History deletion state.
  const [historyMenuOpen, setHistoryMenuOpen] = useState(false);
  const [rowMenuId, setRowMenuId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Pub | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [bulkDeleting, setBulkDeleting] = useState(false);
  const [clearConfirm, setClearConfirm] = useState<"failed" | "all" | null>(null);
  const [clearing, setClearing] = useState(false);

  function toggleChecked(id: string) {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function refreshHistory() {
    await loadHistory(selected?.id);
  }

  async function handleDeleteHistory(id: string) {
    if (deleting) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      const res = await fetch(
        `/api/facebook/manual/publications/${encodeURIComponent(id)}`,
        { method: "DELETE" },
      );
      if (!res.ok) {
        const e = await readError(res);
        if (res.status === 409) {
          throw new Error("Bản đăng đang chờ/đang xử lý. Hãy đợi hoàn tất rồi xoá.");
        }
        throw new Error(e.message || "Không xoá được.");
      }
      setHistory((prev) => prev.filter((h) => h.id !== id));
      setHistoryTotal((t) => Math.max(0, t - 1));
      setChecked((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      if (active?.id === id) setActive(null);
      setDeleteTarget(null);
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Không xoá được.");
    } finally {
      setDeleting(false);
    }
  }

  async function handleBulkDelete() {
    const ids = [...checked];
    if (ids.length === 0 || bulkDeleting) return;
    setBulkDeleting(true);
    setDeleteError(null);
    try {
      const res = await fetch("/api/facebook/manual/publications/bulk-delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids }),
      });
      if (!res.ok) {
        const e = await readError(res);
        throw new Error(e.message || "Không xoá được.");
      }
      const data = (await res.json()) as { deleted: number };
      void data;
      await refreshHistory();
      setChecked(new Set());
      setDeleteTarget(null);
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Không xoá được.");
    } finally {
      setBulkDeleting(false);
    }
  }

  async function handleClearHistory(onlyFailed: boolean) {
    if (clearing) return;
    setClearing(true);
    setDeleteError(null);
    try {
      const res = await fetch("/api/facebook/manual/publications/clear", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          destination_id: selected?.id,
          only_failed: onlyFailed,
          confirm: true,
        }),
      });
      if (!res.ok) {
        const e = await readError(res);
        throw new Error(e.message || "Không xoá được lịch sử.");
      }
      await refreshHistory();
      setChecked(new Set());
      setClearConfirm(null);
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Không xoá được lịch sử.");
    } finally {
      setClearing(false);
    }
  }
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadChannels = useCallback(async () => {
    setLoadError(null);
    try {
      const res = await fetch("/api/facebook/manual/destinations", { cache: "no-store" });
      if (!res.ok) {
        const e = await readError(res);
        throw new Error(e.message);
      }
      const list = (await res.json()) as Channel[];
      setChannels(Array.isArray(list) ? list : []);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Không tải được danh sách kênh.");
      setChannels([]);
    }
  }, []);

  const loadHistory = useCallback(async (channelId?: string) => {
    try {
      const qs = channelId ? `?destination_id=${encodeURIComponent(channelId)}&limit=20` : "?limit=20";
      const res = await fetch(`/api/facebook/manual/publications${qs}`, { cache: "no-store" });
      if (!res.ok) return;
      const data = (await res.json()) as { items: Pub[]; total: number };
      setHistory(Array.isArray(data.items) ? data.items : []);
      setHistoryTotal(data.total ?? 0);
    } catch {
      // Non-fatal.
    }
  }, []);

  useEffect(() => {
    void loadChannels();
    void loadHistory();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [loadChannels, loadHistory]);

  // Returning from Google OAuth: refresh the channel list, toast once,
  // and clean the query param so a reload doesn't re-toast.
  const justConnectedRef = useRef(justConnected);
  useEffect(() => {
    if (!justConnectedRef.current) return;
    justConnectedRef.current = false;
    setConnectedToast(true);
    void (async () => {
      await loadChannels();
      router.replace("/facebook/manual");
      window.setTimeout(() => setConnectedToast(false), 8000);
    })();
  }, [loadChannels, router]);

  async function handleConnect(pipelineId: string) {
    if (connecting) return;
    setConnecting(pipelineId);
    setConnectError(null);
    try {
      // Duplicate safety: reuse a pending (unconnected) destination of this
      // pipeline instead of creating a new one on every retry.
      const listRes = await fetch(
        `/api/facebook/pipelines/${encodeURIComponent(pipelineId)}/youtube-destinations`,
        { cache: "no-store" },
      );
      if (!listRes.ok) {
        const e = await readError(listRes);
        throw new Error(e.message || "Không tải được destinations.");
      }
      const list = (await listRes.json()) as Destination[];
      const pending = Array.isArray(list) ? list.find((d) => !d.connected) : undefined;
      let destinationId = pending?.id;
      if (!destinationId) {
        const createRes = await fetch(
          `/api/facebook/pipelines/${encodeURIComponent(pipelineId)}/youtube-destinations`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ visibility: "public", enabled: true }),
          },
        );
        if (!createRes.ok) {
          const e = await readError(createRes);
          throw new Error(e.message || "Không tạo được destination.");
        }
        const created = (await createRes.json()) as Destination;
        destinationId = created.id;
      }
      if (!destinationId) throw new Error("Không tạo được destination.");
      const oauthRes = await fetch("/api/facebook/oauth/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ destinationId, return_to: "/facebook/manual" }),
      });
      if (!oauthRes.ok) {
        const e = await readError(oauthRes);
        throw new Error(e.message || "Không bắt đầu được OAuth.");
      }
      const data = (await oauthRes.json()) as { authorization_url?: string };
      if (!data.authorization_url) throw new Error("Không nhận được authorization_url.");
      window.location.href = data.authorization_url;
    } catch (err) {
      setConnectError(err instanceof Error ? err.message : "Không kết nối được YouTube.");
      setConnecting(null);
    }
  }

  function pickChannel(ch: Channel) {
    setSelected(ch);
    setUrl("");
    setPreview(null);
    setResolveError(null);
    setTitle("");
    setDescription("");
    setHashtags("");
    setMetaError(null);
    setMode(ch.visibility === "private" ? "private" : "now");
    setPublishError(null);
    setDuplicate(null);
    setActive(null);
    if (pollRef.current) clearInterval(pollRef.current);
    void loadHistory(ch.id);
  }

  async function handleResolve() {
    if (!url.trim() || resolving) return;
    setResolving(true);
    setResolveError(null);
    setPreview(null);
    try {
      const res = await fetch("/api/facebook/manual/resolve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: url.trim() }),
      });
      if (!res.ok) {
        const e = await readError(res);
        throw new Error(e.message);
      }
      const data = (await res.json()) as Preview;
      setPreview(data);
      if (data.caption && !title) setTitle(data.caption.slice(0, 100));
    } catch (err) {
      setResolveError(err instanceof Error ? err.message : "Không nhận diện được video.");
    } finally {
      setResolving(false);
    }
  }

  async function handleGenerate() {
    if (!selected || generating) return;
    setGenerating(true);
    setMetaError(null);
    try {
      const res = await fetch("/api/facebook/manual/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          destination_id: selected.id,
          caption: preview?.caption ?? null,
          source_url: preview?.source_url ?? url.trim(),
        }),
      });
      if (!res.ok) {
        const e = await readError(res);
        throw new Error(e.message);
      }
      const data = (await res.json()) as { title: string; description: string; hashtags: string[] };
      setTitle(data.title ?? "");
      setDescription(data.description ?? "");
      setHashtags((data.hashtags ?? []).join(" "));
    } catch (err) {
      setMetaError(err instanceof Error ? err.message : "AI không tạo được metadata.");
    } finally {
      setGenerating(false);
    }
  }

  function buildPublishAt(): string | null {
    if (mode !== "scheduled") return null;
    if (!schedDate || !schedTime) return null;
    const dt = new Date(`${schedDate}T${schedTime}:00+07:00`);
    if (Number.isNaN(dt.getTime()) || dt.getTime() <= Date.now()) return null;
    return dt.toISOString();
  }

  async function handlePublish(forceDuplicate = false) {
    if (!selected || !preview || publishing) return;
    if (!title.trim()) {
      setPublishError("Tiêu đề không được để trống.");
      return;
    }
    let publishAt: string | null = null;
    if (mode === "scheduled") {
      publishAt = buildPublishAt();
      if (!publishAt) {
        setPublishError("Chọn ngày giờ hẹn trong tương lai (giờ Việt Nam).");
        return;
      }
    }
    setPublishing(true);
    setPublishError(null);
    if (!forceDuplicate) setDuplicate(null);
    try {
      const res = await fetch("/api/facebook/manual/publish", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          destination_id: selected.id,
          source_url: preview.source_url,
          title: title.trim().slice(0, 100),
          description: description.slice(0, 5000),
          hashtags: hashtags.split(/[\s,]+/).map((t) => t.trim()).filter(Boolean),
          visibility: mode === "now" ? "public" : "private",
          publish_at: publishAt,
          caption: preview.caption,
          thumbnail_url: preview.thumbnail_url,
          duration: preview.duration,
          force_duplicate: forceDuplicate,
        }),
      });
      if (!res.ok) {
        const e = await readError(res);
        if (res.status === 409 && e.code === "DUPLICATE_VIDEO") {
          const extra = (e.extra ?? {}) as { existing_id?: unknown; existing_status?: unknown };
          setDuplicate({
            existing_id: typeof extra.existing_id === "string" ? extra.existing_id : "",
            existing_status: typeof extra.existing_status === "string" ? extra.existing_status : "",
          });
          throw new Error("Video này đã được đăng lên kênh này.");
        }
        throw new Error(e.message);
      }
      const data = (await res.json()) as Pub;
      setActive(data);
      setDuplicate(null);
      startPolling(data.id);
      void loadHistory(selected.id);
    } catch (err) {
      setPublishError(err instanceof Error ? err.message : "Không xếp được bản đăng.");
    } finally {
      setPublishing(false);
    }
  }

  function startPolling(id: string) {
    if (pollRef.current) clearInterval(pollRef.current);
    const tick = async () => {
      try {
        const res = await fetch(`/api/facebook/manual/publications/${encodeURIComponent(id)}`, {
          cache: "no-store",
        });
        if (!res.ok) return;
        const data = (await res.json()) as Pub;
        setActive(data);
        if (["scheduled", "published", "failed"].includes(data.status)) {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          void loadHistory(selected?.id);
        }
      } catch {
        // Keep polling on transient errors.
      }
    };
    void tick();
    pollRef.current = setInterval(() => void tick(), 2500);
  }

  async function handleRetry(id: string) {
    try {
      const res = await fetch(
        `/api/facebook/manual/publications/${encodeURIComponent(id)}/retry`,
        { method: "POST" },
      );
      if (!res.ok) {
        const e = await readError(res);
        throw new Error(e.message);
      }
      const data = (await res.json()) as Pub;
      setActive(data);
      startPolling(data.id);
      void loadHistory(selected?.id);
    } catch (err) {
      setPublishError(err instanceof Error ? err.message : "Không retry được.");
    }
  }

  const activeTerminal = active && ["scheduled", "published", "failed"].includes(active.status);

  return (
    <div className="space-y-3">
      <Card>
        <CardHeader
          title="Facebook Manual Publish"
          subtitle="Đăng video Facebook lên YouTube, không qua Inventory/Scheduler"
          icon={<span aria-hidden>📤</span>}
        />
        <div className="space-y-3 p-4 sm:px-5">
          {connectedToast ? (
            <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-3 text-xs font-bold text-emerald-800">
              Đã kết nối YouTube thành công.
            </div>
          ) : null}
          {loadError ? (
            <p className="text-xs text-rose-600">{loadError}</p>
          ) : null}
          {channels === null ? (
            <p className="text-sm text-slate-500">Đang tải danh sách kênh…</p>
          ) : channels.length === 0 ? (
            <div className="p-6 text-center">
              <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-slate-100 text-xl font-extrabold text-slate-400">
                ▶
              </div>
              <p className="mt-3 text-sm font-semibold text-slate-900">Chưa có kênh YouTube nào được kết nối</p>
              <button
                type="button"
                onClick={() => {
                  setConnectError(null);
                  setPickerOpen(true);
                }}
                className="mt-3 inline-flex min-h-[44px] items-center rounded-2xl bg-indigo-600 px-5 py-2.5 text-sm font-extrabold text-white shadow-sm transition hover:bg-indigo-500"
              >
                + Kết nối YouTube
              </button>
            </div>
          ) : (
            <>
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                {selected ? "Kênh đã chọn" : "Chọn kênh YouTube"}
              </p>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {(selected ? [selected] : channels).map((ch) => {
                  const dupCount = ch.channel_id
                    ? (duplicateCounts().get(ch.channel_id) ?? 0)
                    : 0;
                  return (
                  <div
                    key={ch.id}
                    className={`relative flex min-h-[44px] items-center gap-3 rounded-2xl border bg-white p-4 text-left shadow-[0_1px_2px_rgba(15,23,42,0.05)] transition ${
                      selected
                        ? "border-indigo-300 ring-2 ring-indigo-100"
                        : "border-slate-200/90 hover:border-indigo-300 hover:bg-indigo-50/40"
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => !selected && pickChannel(ch)}
                      disabled={!!selected}
                      className="flex min-w-0 flex-1 items-center gap-3 text-left"
                    >
                      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-violet-600 text-lg font-extrabold text-white">
                        {initial(ch.channel_name)}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-extrabold text-slate-900">
                          {ch.channel_name ?? "Unnamed channel"}
                        </span>
                        <span className="block truncate font-mono text-[11px] text-slate-500">
                          {ch.channel_id ?? "—"}
                        </span>
                        {ch.pipeline_name ? (
                          <span className="block truncate text-[11px] text-slate-400">
                            via {ch.pipeline_name}
                          </span>
                        ) : null}
                      </span>
                      <Badge tone={ch.connected ? "green" : "slate"} dot>
                        {ch.connected ? "Connected" : "Chưa kết nối"}
                      </Badge>
                    </button>
                    {dupCount > 1 && !selected ? (
                      <span className="absolute -top-2 left-3 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-extrabold text-amber-800 ring-1 ring-inset ring-amber-200">
                        Duplicate ×{dupCount}
                      </span>
                    ) : null}
                    {!selected ? (
                      <div className="relative shrink-0">
                        <button
                          type="button"
                          title="Tùy chọn kênh"
                          onClick={() => setMenuOpenId(menuOpenId === ch.id ? null : ch.id)}
                          className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-slate-200 bg-white text-sm font-extrabold text-slate-500 shadow-sm transition hover:bg-slate-50 hover:text-slate-700"
                        >
                          ⋯
                        </button>
                        {menuOpenId === ch.id ? (
                          <div className="absolute right-0 z-20 mt-1 w-44 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl">
                            <button
                              type="button"
                              onClick={() => {
                                setMenuOpenId(null);
                                setDisconnectError(null);
                                setConfirmId(ch.id);
                              }}
                              className="flex min-h-[44px] w-full items-center gap-2 px-4 py-2.5 text-left text-xs font-bold text-rose-600 transition hover:bg-rose-50"
                            >
                              🗑 Ngắt kết nối
                            </button>
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                  );
                })}
              </div>
              {selected ? (
                <button
                  type="button"
                  className="text-xs font-semibold text-indigo-600 underline underline-offset-2 hover:text-indigo-800"
                  onClick={() => {
                    setSelected(null);
                    setPreview(null);
                    setActive(null);
                    setDuplicate(null);
                    if (pollRef.current) clearInterval(pollRef.current);
                    void loadHistory();
                  }}
                >
                  ← Chọn kênh khác
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => {
                    setConnectError(null);
                    setPickerOpen(true);
                  }}
                  className="inline-flex min-h-[44px] items-center rounded-2xl border border-dashed border-indigo-300 bg-indigo-50/50 px-4 py-2 text-xs font-extrabold text-indigo-700 transition hover:bg-indigo-50"
                >
                  + Kết nối thêm YouTube
                </button>
              )}
            </>
          )}
        </div>
      </Card>

      {pickerOpen ? (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/50 p-4 backdrop-blur-[2px] sm:items-center">
          <div className="fade-up w-full max-w-md rounded-3xl border border-slate-200 bg-white p-6 shadow-2xl">
            <h3 className="text-base font-extrabold tracking-tight text-slate-900">
              Kênh YouTube này dùng cấu hình AI của pipeline nào?
            </h3>
            <p className="mt-1 text-xs text-slate-500">
              Destination thuộc về pipeline đã chọn. Metadata AI sẽ dùng đúng settings pipeline đó.
            </p>
            {connectError ? (
              <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-600">
                {connectError}
              </div>
            ) : null}
            <div className="mt-4 space-y-2">
              {initialPipelines.length === 0 ? (
                <p className="text-xs text-slate-500">
                  Chưa có pipeline nào. Tạo pipeline trước rồi quay lại.
                </p>
              ) : (
                initialPipelines.map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => void handleConnect(p.id)}
                    disabled={connecting !== null}
                    className="flex min-h-[44px] w-full items-center justify-between gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-left text-sm font-bold text-slate-800 shadow-sm transition hover:border-indigo-300 hover:bg-indigo-50/40 disabled:cursor-wait disabled:opacity-60"
                  >
                    <span className="truncate">{p.name}</span>
                    <span className="shrink-0 text-xs text-slate-400">
                      {connecting === p.id ? "Đang tạo link…" : "→"}
                    </span>
                  </button>
                ))
              )}
            </div>
            <button
              type="button"
              onClick={() => {
                if (connecting) return;
                setPickerOpen(false);
              }}
              className="mt-4 w-full rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-xs font-bold text-slate-600"
            >
              Đóng
            </button>
          </div>
        </div>
      ) : null}

      {confirmId ? (
        (() => {
          const target = (channels ?? []).find((ch) => ch.id === confirmId);
          return (
            <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/50 p-4 backdrop-blur-[2px] sm:items-center">
              <div className="fade-up w-full max-w-md rounded-3xl border border-slate-200 bg-white p-6 shadow-2xl">
                <h3 className="text-base font-extrabold tracking-tight text-slate-900">
                  Ngắt kết nối {target?.channel_name ?? "kênh này"}?
                </h3>
                <p className="mt-1.5 text-xs leading-relaxed text-slate-500">
                  Kênh sẽ biến mất khỏi Manual Publish. Lịch sử đăng cũ vẫn được giữ.
                  {target?.pipeline_name ? (
                    <> Connection này thuộc pipeline <b>{target.pipeline_name}</b>.</>
                  ) : null}
                </p>
                {disconnectError ? (
                  <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-600">
                    {disconnectError}
                  </div>
                ) : null}
                <div className="mt-4 flex gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      if (disconnecting) return;
                      setConfirmId(null);
                    }}
                    className="min-h-[44px] flex-1 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-xs font-bold text-slate-600"
                  >
                    Huỷ
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleDisconnect(confirmId)}
                    disabled={disconnecting}
                    className="min-h-[44px] flex-1 rounded-xl bg-rose-600 px-4 py-2.5 text-xs font-extrabold text-white shadow-sm transition hover:bg-rose-500 disabled:cursor-wait disabled:opacity-70"
                  >
                    {disconnecting ? "Đang ngắt…" : "Ngắt kết nối"}
                  </button>
                </div>
              </div>
            </div>
          );
        })()
      ) : null}

      {selected ? (
        <Card>
          <CardHeader
            title={`Đăng lên: ${selected.channel_name ?? "YouTube"}`}
            subtitle="Dán link → nhận diện → metadata → đăng"
          />
          <div className="space-y-4 p-4 sm:px-5">
            <div>
              <label className={labelCls}>Facebook video URL</label>
              <div className="flex flex-col gap-2 sm:flex-row">
                <input
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void handleResolve();
                  }}
                  placeholder="https://www.facebook.com/reel/…"
                  inputMode="url"
                  className={`${inputCls} min-h-[44px] flex-1`}
                />
                <button
                  type="button"
                  onClick={() => void handleResolve()}
                  disabled={resolving || !url.trim()}
                  className={`${btnSmall} min-h-[44px] shrink-0 disabled:opacity-60`}
                >
                  {resolving ? "Đang nhận diện…" : "Nhận diện"}
                </button>
              </div>
              {resolveError ? (
                <p className="mt-1.5 text-xs text-rose-600">{resolveError}</p>
              ) : null}
              <p className="mt-1.5 text-[11px] text-slate-400">
                Nguồn tải: Shortcut Resolver
              </p>
            </div>

            {preview ? (
              <>
                <div className="flex flex-col gap-3 rounded-2xl border border-slate-200/90 bg-white p-4 sm:flex-row">
                  {preview.thumbnail_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={preview.thumbnail_url}
                      alt="Video thumbnail"
                      className="h-36 w-full shrink-0 rounded-xl object-cover sm:w-48"
                      loading="lazy"
                    />
                  ) : null}
                  <div className="min-w-0 flex-1 text-xs text-slate-600">
                    <p>
                      <span className="font-semibold text-slate-700">Thời lượng:</span>{" "}
                      {formatDuration(preview.duration)}
                    </p>
                    {preview.caption ? (
                      <p className="mt-1.5 line-clamp-4 whitespace-pre-line">{preview.caption}</p>
                    ) : (
                      <p className="mt-1.5 text-slate-400">Video không có caption.</p>
                    )}
                    <p className="mt-1.5 truncate font-mono text-[11px] text-slate-400">
                      {preview.source_url}
                    </p>
                  </div>
                </div>

                <div>
                  <label className="flex cursor-pointer items-center gap-2">
                    <input
                      type="checkbox"
                      checked={aiOn}
                      onChange={(e) => setAiOn(e.target.checked)}
                      className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                    />
                    <span className="text-sm font-medium text-slate-700">
                      Tạo metadata bằng AI
                    </span>
                  </label>
                  {aiOn ? (
                    <button
                      type="button"
                      onClick={() => void handleGenerate()}
                      disabled={generating}
                      className={`${btnSmall} mt-2 disabled:opacity-60`}
                    >
                      {generating ? "AI đang viết…" : "✨ Tạo metadata bằng AI"}
                    </button>
                  ) : null}
                  {metaError ? (
                    <p className="mt-1.5 text-xs text-rose-600">{metaError}</p>
                  ) : null}
                </div>

                <div className="space-y-3">
                  <div>
                    <label className={labelCls}>Title ({title.trim().length}/100)</label>
                    <input
                      value={title}
                      onChange={(e) => setTitle(e.target.value.slice(0, 120))}
                      maxLength={120}
                      className={`${inputCls} min-h-[44px]`}
                    />
                  </div>
                  <div>
                    <label className={labelCls}>Description ({description.length}/5000)</label>
                    <textarea
                      value={description}
                      onChange={(e) => setDescription(e.target.value.slice(0, 5200))}
                      rows={4}
                      maxLength={5200}
                      className={`${inputCls} min-h-[44px]`}
                    />
                  </div>
                  <div>
                    <label className={labelCls}>Hashtags (cách nhau bằng dấu cách)</label>
                    <input
                      value={hashtags}
                      onChange={(e) => setHashtags(e.target.value)}
                      placeholder="#vlog #giaitri"
                      className={`${inputCls} min-h-[44px]`}
                    />
                  </div>
                </div>

                <div>
                  <span className={labelCls}>Chế độ đăng</span>
                  <div className="mt-1.5 flex flex-col gap-2">
                    {(
                      [
                        ["now", "Đăng ngay (Công khai)"],
                        ["private", "Private (chỉ mình bạn)"],
                        ["scheduled", "Hẹn giờ (giờ Việt Nam)"],
                      ] as const
                    ).map(([value, label]) => (
                      <label key={value} className="flex cursor-pointer items-center gap-2">
                        <input
                          type="radio"
                          name="manual-publish-mode"
                          checked={mode === value}
                          onChange={() => setMode(value)}
                          className="border-slate-300 text-indigo-600 focus:ring-indigo-500"
                        />
                        <span className="text-sm text-slate-700">{label}</span>
                      </label>
                    ))}
                  </div>
                  {mode === "scheduled" ? (
                    <div className="mt-2 flex gap-2">
                      <input
                        type="date"
                        value={schedDate}
                        onChange={(e) => setSchedDate(e.target.value)}
                        className={`${inputCls} min-h-[44px] flex-1`}
                      />
                      <input
                        type="time"
                        value={schedTime}
                        onChange={(e) => setSchedTime(e.target.value)}
                        className={`${inputCls} min-h-[44px] flex-1`}
                      />
                    </div>
                  ) : null}
                </div>

                {publishError ? (
                  <p className="text-xs text-rose-600">{publishError}</p>
                ) : null}
                {duplicate ? (
                  <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-xs text-amber-800">
                    <p className="font-bold">Video này đã được đăng lên kênh này.</p>
                    <button
                      type="button"
                      onClick={() => void handlePublish(true)}
                      disabled={publishing}
                      className={`${btnSmall} mt-2 disabled:opacity-60`}
                    >
                      Vẫn đăng lại
                    </button>
                  </div>
                ) : null}
                <button
                  type="button"
                  onClick={() => void handlePublish(false)}
                  disabled={publishing || !title.trim()}
                  className="inline-flex min-h-[48px] w-full items-center justify-center rounded-2xl bg-indigo-600 px-4 py-3 text-sm font-extrabold text-white shadow-sm transition hover:bg-indigo-500 disabled:cursor-wait disabled:opacity-70 sm:w-auto sm:px-8"
                >
                  {publishing ? "Đang xếp hàng…" : "ĐĂNG LÊN YOUTUBE"}
                </button>

                {active ? (
                  <div className="rounded-2xl border border-slate-200/90 bg-slate-50 p-4">
                    <div className="flex items-center gap-2">
                      {!activeTerminal ? (
                        <span className="h-4 w-4 animate-spin rounded-full border-2 border-indigo-300 border-t-indigo-600" aria-hidden />
                      ) : active.status === "failed" ? (
                        <span className="text-base" aria-hidden>❌</span>
                      ) : (
                        <span className="text-base" aria-hidden>✅</span>
                      )}
                      <p className="text-sm font-bold text-slate-900">
                        {stageLabel(active.status, active.stage)}
                      </p>
                    </div>
                    {active.status === "failed" && active.error ? (
                      <p className="mt-1.5 text-xs text-rose-600">{active.error}</p>
                    ) : null}
                    {active.youtube_url ? (
                      <a
                        href={active.youtube_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="mt-1.5 inline-block text-xs font-bold text-indigo-700 underline underline-offset-2"
                      >
                        Mở video YouTube →
                      </a>
                    ) : null}
                  </div>
                ) : null}
              </>
            ) : null}
          </div>
        </Card>
      ) : null}

      <Card>
        <div className="flex items-center justify-between gap-2 border-b border-slate-100 px-4 py-3 sm:px-5">
          <div className="min-w-0">
            <p className="truncate text-sm font-extrabold text-slate-900">Lịch sử đăng thủ công</p>
            {historyTotal ? (
              <p className="text-xs text-slate-500">{historyTotal} bản đăng</p>
            ) : null}
          </div>
          <div className="relative shrink-0">
            <button
              type="button"
              title="Tùy chọn lịch sử"
              onClick={() => setHistoryMenuOpen((v) => !v)}
              className="inline-flex h-11 w-11 items-center justify-center rounded-xl border border-slate-200 bg-white text-sm font-extrabold text-slate-500 shadow-sm transition hover:bg-slate-50 hover:text-slate-700"
            >
              ⋯
            </button>
            {historyMenuOpen ? (
              <div className="absolute right-0 z-20 mt-1 w-52 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl">
                <button
                  type="button"
                  onClick={() => {
                    setHistoryMenuOpen(false);
                    setDeleteError(null);
                    setClearConfirm("failed");
                  }}
                  className="flex min-h-[44px] w-full items-center px-4 py-2.5 text-left text-xs font-bold text-slate-700 transition hover:bg-slate-50"
                >
                  Xoá các bản Failed
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setHistoryMenuOpen(false);
                    setDeleteError(null);
                    setClearConfirm("all");
                  }}
                  className="flex min-h-[44px] w-full items-center px-4 py-2.5 text-left text-xs font-bold text-rose-600 transition hover:bg-rose-50"
                >
                  Xoá toàn bộ lịch sử
                </button>
              </div>
            ) : null}
          </div>
        </div>
        <div className="space-y-2 p-4 sm:px-5">
          {checked.size > 0 ? (
            <div className="flex items-center justify-between gap-2 rounded-2xl border border-indigo-200 bg-indigo-50 px-3 py-2">
              <span className="text-xs font-bold text-indigo-800">
                Đã chọn {checked.size}
              </span>
              <button
                type="button"
                onClick={() => void handleBulkDelete()}
                disabled={bulkDeleting}
                className="inline-flex min-h-[44px] items-center rounded-xl bg-indigo-600 px-3.5 py-2 text-xs font-extrabold text-white shadow-sm transition hover:bg-indigo-500 disabled:cursor-wait disabled:opacity-70"
              >
                {bulkDeleting ? "Đang xoá…" : "Xoá đã chọn"}
              </button>
            </div>
          ) : null}
          {deleteError ? (
            <p className="text-xs text-rose-600">{deleteError}</p>
          ) : null}
          {history.length === 0 ? (
            <p className="py-4 text-center text-xs text-slate-500">Chưa có bản đăng thủ công nào.</p>
          ) : (
            history.map((h) => (
              <div
                key={h.id}
                className="flex flex-wrap items-center gap-2 rounded-2xl border border-slate-200/90 bg-white p-3"
              >
                <input
                  type="checkbox"
                  checked={checked.has(h.id)}
                  onChange={() => toggleChecked(h.id)}
                  title="Chọn để xoá nhiều"
                  className="h-5 w-5 shrink-0 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-bold text-slate-900">
                    {h.youtube_title || "(chưa có tiêu đề)"}
                  </p>
                  <p className="truncate text-xs text-slate-500">
                    {h.channel_name ?? ""} · {h.status}
                    {h.created_at ? ` · ${new Date(h.created_at).toLocaleString("vi-VN")}` : ""}
                  </p>
                  {h.error ? (
                    <p className="truncate text-xs text-rose-600">{h.error}</p>
                  ) : null}
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  {h.youtube_url ? (
                    <a
                      href={h.youtube_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className={btnSmall}
                    >
                      YouTube →
                    </a>
                  ) : null}
                  {h.status === "failed" ? (
                    <button
                      type="button"
                      onClick={() => void handleRetry(h.id)}
                      className={btnSmall}
                    >
                      Retry
                    </button>
                  ) : null}
                  <div className="relative">
                    <button
                      type="button"
                      title="Tùy chọn"
                      onClick={() => setRowMenuId(rowMenuId === h.id ? null : h.id)}
                      className="inline-flex h-11 w-11 items-center justify-center rounded-xl border border-slate-200 bg-white text-sm font-extrabold text-slate-500 shadow-sm transition hover:bg-slate-50 hover:text-slate-700"
                    >
                      ⋯
                    </button>
                    {rowMenuId === h.id ? (
                      <div className="absolute right-0 z-20 mt-1 w-44 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl">
                        <button
                          type="button"
                          onClick={() => {
                            setRowMenuId(null);
                            setDeleteError(null);
                            setDeleteTarget(h);
                          }}
                          className="flex min-h-[44px] w-full items-center gap-2 px-4 py-2.5 text-left text-xs font-bold text-rose-600 transition hover:bg-rose-50"
                        >
                          🗑 Xoá khỏi lịch sử
                        </button>
                      </div>
                    ) : null}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </Card>

      {deleteTarget ? (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/50 p-4 backdrop-blur-[2px] sm:items-center">
          <div className="fade-up w-full max-w-md rounded-3xl border border-slate-200 bg-white p-6 shadow-2xl">
            <h3 className="text-base font-extrabold tracking-tight text-slate-900">
              Xoá bản ghi này khỏi lịch sử?
            </h3>
            <p className="mt-1.5 text-xs leading-relaxed text-slate-500">
              Chỉ xoá lịch sử trong hệ thống. Video đã đăng trên YouTube sẽ{" "}
              <b>KHÔNG</b> bị xoá.
            </p>
            <p className="mt-2 truncate text-xs font-bold text-slate-700">
              {deleteTarget.youtube_title || deleteTarget.id}
            </p>
            {deleteError ? (
              <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-600">
                {deleteError}
              </div>
            ) : null}
            <div className="mt-4 flex gap-2">
              <button
                type="button"
                onClick={() => {
                  if (deleting) return;
                  setDeleteTarget(null);
                }}
                className="min-h-[44px] flex-1 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-xs font-bold text-slate-600"
              >
                Huỷ
              </button>
              <button
                type="button"
                onClick={() => void handleDeleteHistory(deleteTarget.id)}
                disabled={deleting}
                className="min-h-[44px] flex-1 rounded-xl bg-rose-600 px-4 py-2.5 text-xs font-extrabold text-white shadow-sm transition hover:bg-rose-500 disabled:cursor-wait disabled:opacity-70"
              >
                {deleting ? "Đang xoá…" : "Xoá"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {clearConfirm ? (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/50 p-4 backdrop-blur-[2px] sm:items-center">
          <div className="fade-up w-full max-w-md rounded-3xl border border-slate-200 bg-white p-6 shadow-2xl">
            <h3 className="text-base font-extrabold tracking-tight text-slate-900">
              {clearConfirm === "failed"
                ? "Xoá các bản Failed khỏi lịch sử?"
                : "Xoá toàn bộ lịch sử Manual Publish?"}
            </h3>
            <p className="mt-1.5 text-xs leading-relaxed text-slate-500">
              {clearConfirm === "failed"
                ? "Chỉ xoá các bản failed. Video YouTube sẽ không bị ảnh hưởng."
                : "Chỉ xoá các bản published/scheduled/failed. Bản đang chờ/xử lý được giữ lại. Video YouTube sẽ không bị ảnh hưởng."}
            </p>
            {deleteError ? (
              <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-600">
                {deleteError}
              </div>
            ) : null}
            <div className="mt-4 flex gap-2">
              <button
                type="button"
                onClick={() => {
                  if (clearing) return;
                  setClearConfirm(null);
                }}
                className="min-h-[44px] flex-1 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-xs font-bold text-slate-600"
              >
                Huỷ
              </button>
              <button
                type="button"
                onClick={() => void handleClearHistory(clearConfirm === "failed")}
                disabled={clearing}
                className="min-h-[44px] flex-1 rounded-xl bg-rose-600 px-4 py-2.5 text-xs font-extrabold text-white shadow-sm transition hover:bg-rose-500 disabled:cursor-wait disabled:opacity-70"
              >
                {clearing ? "Đang xoá…" : "Xoá"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
