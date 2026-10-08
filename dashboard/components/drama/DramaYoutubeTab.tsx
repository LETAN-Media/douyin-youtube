"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Card, CardHeader, btnSmall } from "@/components/ui";
import type { DramaYoutubeDestinationDto } from "@/lib/drama-api";

const VISIBILITIES = [
  { value: "public", label: "Công khai" },
  { value: "unlisted", label: "Không công khai" },
  { value: "private", label: "Riêng tư" },
];

function initial(name: string | null): string {
  const c = (name ?? "?").trim().charAt(0).toUpperCase();
  return c || "?";
}

async function readError(res: Response): Promise<string> {
  try {
    const data = (await res.json()) as { error?: unknown; message?: unknown };
    if (typeof data?.error === "string" && data.error.trim()) return data.error;
    if (typeof data?.message === "string" && data.message.trim()) return data.message;
  } catch {
    // ignore
  }
  return `HTTP ${res.status}`;
}

export function DramaYoutubeTab({ pipelineId }: { pipelineId: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [destinations, setDestinations] = useState<DramaYoutubeDestinationDto[] | null>(null);
  const [channels, setChannels] = useState<DramaYoutubeDestinationDto[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [visibility, setVisibility] = useState("public");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [destRes, chanRes, setRes] = await Promise.all([
        fetch(`/api/drama/pipelines/${encodeURIComponent(pipelineId)}/youtube-destinations`, {
          cache: "no-store",
        }),
        fetch("/api/drama/youtube/destinations", { cache: "no-store" }),
        fetch(`/api/drama/pipelines/${encodeURIComponent(pipelineId)}/processing-settings`, {
          cache: "no-store",
        }),
      ]);
      if (destRes.ok) {
        const list = (await destRes.json()) as DramaYoutubeDestinationDto[];
        setDestinations(Array.isArray(list) ? list : []);
      } else {
        setDestinations([]);
      }
      if (chanRes.ok) {
        const list = (await chanRes.json()) as DramaYoutubeDestinationDto[];
        setChannels(Array.isArray(list) ? list : []);
      }
      if (setRes.ok) {
        const s = (await setRes.json()) as { youtube_destination_id?: string | null };
        setSelectedId(typeof s.youtube_destination_id === "string" ? s.youtube_destination_id : null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không tải được destinations.");
    }
  }, [pipelineId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (searchParams.get("youtube_connected") === "1") {
      setToast("Đã kết nối YouTube thành công.");
      void load().then(() => {
        router.replace(`/drama/${encodeURIComponent(pipelineId)}?tab=youtube`);
        window.setTimeout(() => setToast(null), 8000);
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleConnect() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/drama/youtube/oauth/start?pipeline_id=${encodeURIComponent(pipelineId)}` +
          `&visibility=${encodeURIComponent(visibility)}`,
      );
      if (!res.ok) throw new Error(await readError(res));
      const data = (await res.json()) as { authorization_url?: string };
      if (!data.authorization_url) throw new Error("Không nhận được authorization_url.");
      window.location.href = data.authorization_url;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không bắt đầu được OAuth.");
      setBusy(false);
    }
  }

  async function handleSelect(destinationId: string) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/drama/pipelines/${encodeURIComponent(pipelineId)}/processing-settings`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ youtube_destination_id: destinationId }),
        },
      );
      if (!res.ok) throw new Error(await readError(res));
      setSelectedId(destinationId);
      setToast("Đã chọn kênh cho pipeline này.");
      window.setTimeout(() => setToast(null), 5000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không chọn được kênh.");
    } finally {
      setBusy(false);
    }
  }

  async function handleDisconnect(destinationId: string) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/drama/youtube-destinations/${encodeURIComponent(destinationId)}`,
        { method: "DELETE" },
      );
      if (!res.ok) throw new Error(await readError(res));
      setConfirmId(null);
      if (selectedId === destinationId) setSelectedId(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không ngắt kết nối được.");
    } finally {
      setBusy(false);
    }
  }

  const others = channels.filter(
    (ch) => !destinations?.some((d) => d.id === ch.id),
  );

  return (
    <div className="space-y-3">
      <Card>
        <CardHeader
          title="YouTube"
          subtitle="Kết nối kênh và chọn destination cho pipeline này"
        />
        <div className="space-y-3 p-4 sm:px-5">
          {toast ? (
            <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-3 text-xs font-bold text-emerald-800">
              {toast}
            </div>
          ) : null}
          {error ? <p className="text-xs text-rose-600">{error}</p> : null}

          <div className="flex flex-col gap-2 rounded-2xl border border-slate-200/90 bg-slate-50/60 p-4 sm:flex-row sm:items-center">
            <div className="flex min-w-0 flex-1 items-center gap-2">
              <label className="shrink-0 text-xs font-extrabold uppercase tracking-wider text-slate-500">
                Chế độ hiển thị
              </label>
              <select
                value={visibility}
                onChange={(e) => setVisibility(e.target.value)}
                className="min-h-[44px] flex-1 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-bold text-slate-900 outline-none focus:border-indigo-500"
              >
                {VISIBILITIES.map((v) => (
                  <option key={v.value} value={v.value}>
                    {v.label}
                  </option>
                ))}
              </select>
            </div>
            <button
              type="button"
              onClick={() => void handleConnect()}
              disabled={busy}
              className="inline-flex min-h-[44px] shrink-0 items-center justify-center rounded-2xl bg-indigo-600 px-5 py-2.5 text-sm font-extrabold text-white shadow-sm transition hover:bg-indigo-500 disabled:cursor-wait disabled:opacity-70"
            >
              {busy ? "Đang tạo link…" : "+ Kết nối YouTube"}
            </button>
          </div>

          <p className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
            Kênh của pipeline này ({destinations?.length ?? 0})
          </p>
          {destinations === null ? (
            <p className="text-xs text-slate-500">Đang tải…</p>
          ) : destinations.length === 0 ? (
            <p className="rounded-2xl border border-dashed border-slate-200 p-4 text-center text-xs text-slate-500">
              Chưa có kênh nào. Bấm “+ Kết nối YouTube” ở trên.
            </p>
          ) : (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {destinations.map((d) => (
                <ChannelCard
                  key={d.id}
                  channel={d}
                  selected={selectedId === d.id}
                  busy={busy}
                  onSelect={() => void handleSelect(d.id)}
                  onDisconnect={() => setConfirmId(d.id)}
                />
              ))}
            </div>
          )}

          {others.length > 0 ? (
            <>
              <p className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
                Kênh đã login ở pipeline khác — chọn ngay
              </p>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {others.map((d) => (
                  <ChannelCard
                    key={d.id}
                    channel={d}
                    selected={false}
                    busy={busy}
                    onSelect={() => void handleSelect(d.id)}
                    hideDisconnect
                  />
                ))}
              </div>
            </>
          ) : null}
        </div>
      </Card>

      {confirmId ? (
        (() => {
          const target = destinations?.find((d) => d.id === confirmId);
          return (
            <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/50 p-4 backdrop-blur-[2px] sm:items-center">
              <div className="fade-up w-full max-w-md rounded-3xl border border-slate-200 bg-white p-6 shadow-2xl">
                <h3 className="text-base font-extrabold tracking-tight text-slate-900">
                  Ngắt kết nối {target?.channel_title ?? "kênh này"}?
                </h3>
                <p className="mt-1.5 text-xs leading-relaxed text-slate-500">
                  Kênh sẽ biến mất khỏi danh sách. Lịch sử job cũ vẫn được giữ.
                </p>
                <div className="mt-4 flex gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      if (!busy) setConfirmId(null);
                    }}
                    className="min-h-[44px] flex-1 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-xs font-bold text-slate-600"
                  >
                    Huỷ
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleDisconnect(confirmId)}
                    disabled={busy}
                    className="min-h-[44px] flex-1 rounded-xl bg-rose-600 px-4 py-2.5 text-xs font-extrabold text-white shadow-sm transition hover:bg-rose-500 disabled:cursor-wait disabled:opacity-70"
                  >
                    {busy ? "Đang ngắt…" : "Ngắt kết nối"}
                  </button>
                </div>
              </div>
            </div>
          );
        })()
      ) : null}
    </div>
  );
}

function ChannelCard({
  channel,
  selected,
  busy,
  onSelect,
  onDisconnect,
  hideDisconnect,
}: {
  channel: DramaYoutubeDestinationDto;
  selected: boolean;
  busy: boolean;
  onSelect: () => void;
  onDisconnect?: () => void;
  hideDisconnect?: boolean;
}) {
  return (
    <div
      className={`relative flex min-h-[44px] items-center gap-3 rounded-2xl border bg-white p-4 shadow-[0_1px_2px_rgba(15,23,42,0.05)] ${
        selected ? "border-indigo-400 ring-2 ring-indigo-100" : "border-slate-200/90"
      }`}
    >
      {channel.channel_thumbnail ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={channel.channel_thumbnail}
          alt={channel.channel_title ?? "YouTube channel"}
          className="h-11 w-11 shrink-0 rounded-full object-cover ring-1 ring-slate-200"
          loading="lazy"
        />
      ) : (
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-rose-500 to-red-600 text-lg font-extrabold text-white">
          {(channel.channel_title ?? "?").trim().charAt(0).toUpperCase() || "?"}
        </span>
      )}
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-extrabold text-slate-900">
          {channel.channel_title ?? "Unnamed channel"}
        </p>
        <p className="truncate font-mono text-[11px] text-slate-500">
          {channel.channel_id ?? (channel.connected ? "…" : "chưa kết nối")}
        </p>
      </div>
      {selected ? (
        <span className="shrink-0 rounded-full bg-indigo-600 px-2.5 py-1 text-[10px] font-extrabold text-white">
          Đang chọn
        </span>
      ) : channel.connected ? (
        <button
          type="button"
          onClick={onSelect}
          disabled={busy}
          className={`${btnSmall} shrink-0 disabled:opacity-60`}
        >
          Chọn kênh
        </button>
      ) : (
        <span className="shrink-0 rounded-full bg-slate-100 px-2.5 py-1 text-[10px] font-extrabold text-slate-500">
          Chưa xong OAuth
        </span>
      )}
      {!hideDisconnect && onDisconnect ? (
        <button
          type="button"
          title="Ngắt kết nối"
          onClick={onDisconnect}
          className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-slate-200 bg-white text-sm font-extrabold text-slate-400 shadow-sm transition hover:bg-rose-50 hover:text-rose-600"
        >
          ✕
        </button>
      ) : null}
    </div>
  );
}
