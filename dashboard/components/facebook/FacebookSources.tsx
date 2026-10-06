"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Card, CardHeader, Badge, btnSmall, inputCls, labelCls } from "@/components/ui";
import { IconSources } from "@/components/icons";
import type { FacebookSourceDto } from "@/lib/facebook-api";

function sourceStatus(s: FacebookSourceDto): { tone: string; label: string } {
  if (s.last_scan_status === "failed") return { tone: "red", label: "Error" };
  if (s.last_scan_status === "running" || s.last_scan_status === "queued") {
    return { tone: "amber", label: "Scanning" };
  }
  return { tone: "green", label: "Connected" };
}

type AddResult = { url: string; ok: boolean; message: string };

async function parseErrorMessage(res: Response): Promise<string> {
  try {
    const data = (await res.json()) as { error?: unknown; message?: unknown };
    if (typeof data?.error === "string" && data.error.trim()) return data.error;
    if (typeof data?.message === "string" && data.message.trim()) return data.message;
  } catch {
    // ignore
  }
  return `HTTP ${res.status}`;
}

export function FacebookSources({
  sources,
  pipelineId,
}: {
  sources: FacebookSourceDto[];
  pipelineId: string;
}) {
  const router = useRouter();
  const [scanning, setScanning] = useState<Record<string, string>>({});
  const [bulkUrls, setBulkUrls] = useState("");
  const [adding, setAdding] = useState(false);
  const [addResults, setAddResults] = useState<AddResult[]>([]);
  const [items, setItems] = useState<FacebookSourceDto[]>(sources);
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<FacebookSourceDto | null>(null);
  const [working, setWorking] = useState(false);
  const [rowError, setRowError] = useState<string | null>(null);

  // Keep local list in sync when the server re-renders with fresh data.
  useEffect(() => {
    setItems(sources);
  }, [sources]);

  async function addSources() {
    const urls = bulkUrls
      .split("\n")
      .map((u) => u.trim())
      .filter(Boolean)
      .slice(0, 10);
    if (urls.length === 0 || adding) return;
    setAdding(true);
    setAddResults([]);
    const results: AddResult[] = [];
    for (const url of urls) {
      try {
        const res = await fetch(
          `/api/facebook/pipelines/${encodeURIComponent(pipelineId)}/sources`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url }),
          },
        );
        if (!res.ok) {
          const message = await parseErrorMessage(res);
          results.push({ url, ok: false, message });
        } else {
          results.push({ url, ok: true, message: "Đã thêm nguồn." });
        }
      } catch (err) {
        results.push({
          url,
          ok: false,
          message: err instanceof Error ? err.message : "Lỗi mạng.",
        });
      }
      setAddResults([...results]);
    }
    setAdding(false);
    if (results.some((r) => r.ok)) {
      setBulkUrls("");
      router.refresh();
    }
  }

  async function toggleEnabled(source: FacebookSourceDto) {
    if (working) return;
    setWorking(true);
    setRowError(null);
    setMenuOpenId(null);
    const next = !source.enabled;
    try {
      const res = await fetch(`/api/facebook/sources/${encodeURIComponent(source.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: next }),
      });
      if (!res.ok) {
        throw new Error(await parseErrorMessage(res));
      }
      setItems((prev) => prev.map((s) => (s.id === source.id ? { ...s, enabled: next } : s)));
      router.refresh();
    } catch (err) {
      setRowError(err instanceof Error ? err.message : "Không cập nhật được nguồn.");
    } finally {
      setWorking(false);
    }
  }

  async function deleteSource(sourceId: string) {
    if (working) return;
    setWorking(true);
    setRowError(null);
    try {
      const res = await fetch(`/api/facebook/sources/${encodeURIComponent(sourceId)}`, {
        method: "DELETE",
      });
      if (!res.ok) {
        const message = await parseErrorMessage(res);
        if (res.status === 409) throw new Error(message);
        throw new Error(message);
      }
      setItems((prev) => prev.filter((s) => s.id !== sourceId));
      setConfirmDelete(null);
      router.refresh();
    } catch (err) {
      setRowError(err instanceof Error ? err.message : "Không xoá được nguồn.");
    } finally {
      setWorking(false);
    }
  }

  async function scanNow(sourceId: string) {   setScanning((m) => ({ ...m, [sourceId]: "starting" }));
    try {
      const res = await fetch("/api/facebook/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sourceId }),
      });
      const data = (await res.json()) as { error?: string };
      setScanning((m) => ({
        ...m,
        [sourceId]: res.ok ? "started" : `error: ${data.error ?? res.status}`,
      }));
    } catch {
      setScanning((m) => ({ ...m, [sourceId]: "error: network" }));
    }
  }

  return (
    <Card>
      <CardHeader
        title={`Facebook Sources (${items.length})`}
        subtitle="Quản lý Fanpage nguồn cho pipeline này"
        icon={<IconSources size={16} />}
      />
      <div className="space-y-3 p-4 sm:px-5">
        <div className="rounded-2xl border border-slate-200/90 bg-slate-50/60 p-4">
          <label className={labelCls}>Thêm nguồn Facebook (mỗi dòng 1 link, tối đa 10)</label>
          <textarea
            value={bulkUrls}
            onChange={(e) => setBulkUrls(e.target.value)}
            placeholder={"https://www.facebook.com/PageMot/reels/\nhttps://www.facebook.com/6159.../reels/"}
            rows={3}
            disabled={adding}
            className={`${inputCls} min-h-[44px] font-mono text-xs`}
          />
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => void addSources()}
              disabled={adding || !bulkUrls.trim()}
              className={`${btnSmall} min-h-[44px] disabled:opacity-60`}
            >
              {adding ? "Đang thêm…" : "+ Thêm nguồn"}
            </button>
          </div>
          {addResults.length > 0 ? (
            <ul className="mt-2 space-y-1">
              {addResults.map((r, i) => (
                <li key={`${i}-${r.url}`} className="truncate text-xs">
                  <span className={r.ok ? "font-bold text-emerald-600" : "font-bold text-rose-600"}>
                    {r.ok ? "✓" : "✗"}
                  </span>{" "}
                  <span className="font-mono text-slate-500">{r.url}</span>
                  <span className="text-slate-500"> — {r.message}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
        {items.length === 0 && addResults.length === 0 ? (
          <div className="p-6 text-center text-sm text-slate-500">Chưa có Facebook source</div>
        ) : null}
        <div className="space-y-3 p-4 sm:px-5">
          {items.map((s) => {
            const st = sourceStatus(s);
            const state = scanning[s.id];
            return (
              <div key={s.id} className="rounded-2xl border border-slate-200/90 bg-white p-4 shadow-[0_1px_2px_rgba(15,23,42,0.05)]">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-extrabold text-slate-900">Facebook Page</p>
                    <p className="mt-1 text-xs text-slate-500">Fanpage: {s.page_name ?? "—"}</p>
                    <p className="text-xs text-slate-500">Page ID: {s.page_id}</p>
                    {s.reels_url ? (
                      <p className="truncate text-xs text-slate-400">{s.reels_url}</p>
                    ) : null}
                  </div>
                  <Badge tone={st.tone} dot>
                    {st.label}
                  </Badge>
                </div>
                <div className="mt-3 flex flex-wrap gap-3 text-xs text-slate-600">
                  <span>Enabled: {s.enabled ? "ON" : "OFF"}</span>
                  <span>
                    Last Scan: {s.last_scan_at ? new Date(s.last_scan_at).toLocaleString() : "—"}
                  </span>
                  <span>Status: {s.last_scan_status ?? "—"}</span>
                  <span>Videos Found: {s.discovered_total}</span>
                  {s.crawl_complete ? <span>Crawl: complete</span> : null}
                </div>
                {s.last_scan_error ? (
                  <p className="mt-2 text-xs text-rose-600">{s.last_scan_error}</p>
                ) : null}
                <div className="mt-3 flex flex-wrap gap-1.5">
                  <button
                    type="button"
                    className={btnSmall}
                    disabled={!s.enabled || state === "starting"}
                    onClick={() => scanNow(s.id)}
                  >
                    {state === "starting" ? "Đang bắt đầu…" : "Quét ngay"}
                  </button>
                  <div className="relative">
                    <button
                      type="button"
                      title="Tùy chọn nguồn"
                      onClick={() => setMenuOpenId(menuOpenId === s.id ? null : s.id)}
                      className="inline-flex h-9 min-w-[44px] items-center justify-center rounded-xl border border-slate-200 bg-white px-2 text-sm font-extrabold text-slate-500 shadow-sm transition hover:bg-slate-50 hover:text-slate-700"
                    >
                      ⋯
                    </button>
                    {menuOpenId === s.id ? (
                      <div className="absolute right-0 z-20 mt-1 w-48 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl">
                        <button
                          type="button"
                          onClick={() => void toggleEnabled(s)}
                          disabled={working}
                          className="flex min-h-[44px] w-full items-center px-4 py-2.5 text-left text-xs font-bold text-slate-700 transition hover:bg-slate-50 disabled:opacity-60"
                        >
                          {s.enabled ? "⏸ Tắt nguồn" : "▶ Bật nguồn"}
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setMenuOpenId(null);
                            setRowError(null);
                            setConfirmDelete(s);
                          }}
                          className="flex min-h-[44px] w-full items-center px-4 py-2.5 text-left text-xs font-bold text-rose-600 transition hover:bg-rose-50"
                        >
                          🗑 Xoá nguồn
                        </button>
                      </div>
                    ) : null}
                  </div>
                </div>
                {state && state !== "starting" ? (
                  <p className="mt-2 text-xs text-slate-500">
                    {state === "started" ? "Đã xếp hàng scan." : state}
                  </p>
                ) : null}
                {rowError ? (
                  <p className="mt-2 text-xs text-rose-600">{rowError}</p>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>

      {confirmDelete ? (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/50 p-4 backdrop-blur-[2px] sm:items-center">
          <div className="fade-up w-full max-w-md rounded-3xl border border-slate-200 bg-white p-6 shadow-2xl">
            <h3 className="text-base font-extrabold tracking-tight text-slate-900">
              Xoá nguồn {confirmDelete.page_name ?? confirmDelete.page_id}?
            </h3>
            <p className="mt-1.5 text-xs leading-relaxed text-slate-500">
              Nguồn sẽ bị xoá khỏi pipeline. Chỉ xoá được nguồn chưa có video nào —
              nguồn đã có video thì hãy <b>Tắt nguồn</b> thay vì xoá để giữ Inventory.
            </p>
            <div className="mt-4 flex gap-2">
              <button
                type="button"
                onClick={() => {
                  if (working) return;
                  setConfirmDelete(null);
                }}
                className="min-h-[44px] flex-1 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-xs font-bold text-slate-600"
              >
                Huỷ
              </button>
              <button
                type="button"
                onClick={() => void deleteSource(confirmDelete.id)}
                disabled={working}
                className="min-h-[44px] flex-1 rounded-xl bg-rose-600 px-4 py-2.5 text-xs font-extrabold text-white shadow-sm transition hover:bg-rose-500 disabled:cursor-wait disabled:opacity-70"
              >
                {working ? "Đang xoá…" : "Xoá"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </Card>
  );
}
