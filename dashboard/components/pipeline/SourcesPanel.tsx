"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useToast } from "@/components/Toast";
import { ConfirmButton } from "@/components/ConfirmButton";
import {
  Badge,
  Card,
  CardHeader,
  EmptyState,
  btnPrimary,
  btnSecondary,
  btnSmall,
  inputCls,
  labelCls,
} from "@/components/ui";
import {
  actionCreateSource,
  actionDeleteSource,
  actionGetDouyinSession,
  actionGetSourceStatus,
  actionSyncPipeline,
  actionSyncSource,
  actionToggleSource,
} from "@/lib/actions";
import { formatDateTime } from "@/lib/format";
import type { DouyinSource } from "@/lib/types";
import { DouyinSessionPanel } from "./DouyinSessionPanel";
import { IconSources } from "@/components/icons";

export function SourcesPanel({
  pipelineId,
  sources,
}: {
  pipelineId: string;
  sources: DouyinSource[];
}) {
  const { toast } = useToast();
  const router = useRouter();
  const [, start] = useTransition();
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  // Optimistic local list: single-tap toggle/delete feel instant.
  const [items, setItems] = useState(sources);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- refresh list on server data change
    setItems(sources);
  }, [sources]);
  const pollTimers = useRef<ReturnType<typeof setTimeout>[]>([]);
  useEffect(() => () => {
    pollTimers.current.forEach(clearTimeout);
  }, []);

  const isBusy = (k: string) => pendingKey === k;

  const pollSync = (sourceId: string, attempt = 0) => {
    if (attempt >= 20) {
      setPendingKey(null);
      router.refresh();
      return;
    }
    const t = setTimeout(() => {
      start(async () => {
        const r = await actionGetSourceStatus(sourceId);
        if (!r.ok) {
          setPendingKey(null);
          router.refresh();
          return;
        }
        const st = r.status ?? "";
        setItems((prev) =>
          prev.map((s) =>
            s.id === sourceId
              ? { ...s, inventory_sync_status: st, inventory_sync_error: r.errorDetail ?? s.inventory_sync_error }
              : s,
          ),
        );
        if (st === "queued" || st === "running" || st === "syncing") {
          pollSync(sourceId, attempt + 1);
        } else {
          setPendingKey(null);
          if (st === "completed") toast("Sync xong.", "success");
          else if (st === "auth_required") toast("Cần Douyin login (QR).", "error");
          else if (st === "failed") toast(r.errorDetail || "Sync thất bại.", "error");
          router.refresh();
        }
      });
    }, 3000);
    pollTimers.current.push(t);
  };

  const doSync = (s: DouyinSource) => {
    const key = `sync:${s.id}`;
    if (pendingKey) return;
    setPendingKey(key);
    // Optimistic: show queued immediately, disable button, spinner.
    setItems((prev) =>
      prev.map((x) => (x.id === s.id ? { ...x, inventory_sync_status: "queued", inventory_sync_error: null } : x)),
    );
    start(async () => {
      const r = await actionSyncSource(pipelineId, s.id);
      if (!r.ok) {
        toast(r.error, "error");
        setPendingKey(null);
        router.refresh();
        return;
      }
      toast("Đã xếp hàng sync — đang quét nền.", "success");
      pollSync(s.id);
    });
  };

  const doSyncAll = () => {
    if (pendingKey) return;
    setPendingKey("syncAll");
    start(async () => {
      const r = await actionSyncPipeline(pipelineId);
      setPendingKey(null);
      toast(r.ok ? "Đã xếp hàng sync tất cả — quét nền." : r.error, r.ok ? "success" : "error");
      router.refresh();
    });
  };

  const doToggle = (s: DouyinSource) => {
    const key = `toggle:${s.id}`;
    if (pendingKey) return;
    setPendingKey(key);
    const next = !s.enabled;
    setItems((prev) => prev.map((x) => (x.id === s.id ? { ...x, enabled: next } : x)));
    start(async () => {
      const r = await actionToggleSource(pipelineId, s.id, next);
      setPendingKey(null);
      toast(r.ok ? (next ? "Đã enable." : "Đã disable.") : r.error, r.ok ? "success" : "error");
      if (!r.ok) {
        setItems((prev) => prev.map((x) => (x.id === s.id ? { ...x, enabled: !next } : x)));
      }
      router.refresh();
    });
  };

  const doDelete = async (s: DouyinSource) => {
    const r = await actionDeleteSource(pipelineId, s.id);
    if (r.ok) {
      setItems((prev) => prev.filter((x) => x.id !== s.id));
      router.refresh();
    }
    return r;
  };

  const validateSession = () => {
    if (pendingKey) return;
    setPendingKey("validate");
    start(async () => {
      const r = await actionGetDouyinSession();
      setPendingKey(null);
      if (r.ok) {
        if (r.cookieRequired === true) {
          toast("Cookie required: anonymous access bị chặn, cần DOUYIN_COOKIES_B64.", "error");
        } else if (r.anonymousAccess === true) {
          toast("Anonymous access hoạt động — không cần cookie.", "success");
        } else {
          toast("Douyin session hợp lệ.", "success");
        }
      } else {
        toast(r.error, "error");
      }
    });
  };

  return (
    <div className="space-y-4">
      <DouyinSessionPanel pipelineId={pipelineId} />
      <Card>
        <CardHeader
          title={`Douyin Sources (${items.length})`}
          subtitle="Paste profile URL → Sync Now → View Inventory"
          icon={<IconSources size={16} />}
          action={
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className={btnSmall}
                disabled={pendingKey !== null}
                onClick={doSyncAll}
              >
                {isBusy("syncAll") ? "Đang xếp hàng…" : "Sync all"}
              </button>
              <button
                type="button"
                className={btnSmall}
                disabled={pendingKey !== null}
                onClick={validateSession}
              >
                {isBusy("validate") ? "…" : "Validate Session"}
              </button>
              <button
                type="button"
                className={btnSmall}
                onClick={() => setShowAdd((v) => !v)}
              >
                + Add Douyin Source
              </button>
            </div>
          }
        />
        {showAdd ? (
          <form
            className="grid gap-3 border-b border-slate-100 p-4 sm:grid-cols-[1fr_2fr_auto] sm:items-end sm:px-5"
            onSubmit={(e) => {
              e.preventDefault();
              if (pendingKey) return;
              const formEl = e.currentTarget;
              const form = new FormData(formEl);
              setPendingKey("create");
              start(async () => {
                const r = await actionCreateSource(pipelineId, form);
                setPendingKey(null);
                toast(r.ok ? "Đã thêm source — đang quét nền." : r.error, r.ok ? "success" : "error");
                if (r.ok) {
                  formEl.reset();
                  setShowAdd(false);
                  router.refresh();
                }
              });
            }}
          >
            <div>
              <label className={labelCls} htmlFor="src-name">Name</label>
              <input id="src-name" name="name" required placeholder="Kênh A" className={inputCls} />
            </div>
            <div>
              <label className={labelCls} htmlFor="src-url">Profile URL</label>
              <input
                id="src-url"
                name="profile_url"
                required
                placeholder="https://www.douyin.com/user/..."
                className={inputCls}
              />
            </div>
            <button type="submit" disabled={pendingKey !== null} className={`${btnPrimary} min-h-[44px]`}>
              {isBusy("create") ? "Đang thêm…" : "Add"}
            </button>
          </form>
        ) : null}

        {items.length === 0 ? (
          <EmptyState
            title="Chưa có Douyin source"
            hint="Thêm profile URL Douyin để bắt đầu quét inventory."
          />
        ) : (
          <>
            {/* Desktop table */}
            <div className="hidden overflow-x-auto md:block">
              <table className="w-full text-sm">
                <thead className="bg-slate-50/70">
                  <tr className="border-b border-slate-100 text-left text-[11px] uppercase tracking-[0.08em] text-slate-400">
                    <th className="px-5 py-3 font-bold">Name</th>
                    <th className="px-3 py-3 font-bold">Profile</th>
                    <th className="px-3 py-3 font-bold">Sync</th>
                    <th className="px-3 py-3 font-bold">Last sync</th>
                    <th className="px-3 py-3 text-right font-bold">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {items.map((s) => (
                    <tr key={s.id} className="align-top transition hover:bg-indigo-50/40">
                      <td className="px-5 py-3">
                        <p className="font-bold text-slate-900">{s.name}</p>
                        <p className="mt-1">
                          {s.enabled ? <Badge tone="green" dot>Enabled</Badge> : <Badge tone="slate" dot>Disabled</Badge>}
                        </p>
                      </td>
                      <td className="max-w-56 px-3 py-3">
                        <p className="break-all text-xs text-slate-600">{s.profile_url ?? "—"}</p>
                        {s.douyin_sec_uid ? (
                          <p className="mt-1 text-[11px] text-slate-400">sec_uid: {s.douyin_sec_uid.slice(0, 18)}…</p>
                        ) : null}
                      </td>
                      <td className="px-3 py-3">
                        <SyncBadge status={s.inventory_sync_status} />
                        {s.inventory_sync_status === "auth_required" ? (
                          <p className="mt-1">
                            <Badge tone="red">Douyin Login Required</Badge>
                          </p>
                        ) : null}
                        {typeof s.inventory_count === "number" ? (
                          <p className="mt-1 text-xs text-slate-600">
                            Inventory: {s.inventory_count}
                          </p>
                        ) : null}
                        {s.inventory_sync_error ? (
                          <p className="mt-1 max-w-56 break-words text-[11px] text-red-600">
                            {s.inventory_sync_error.slice(0, 200)}
                          </p>
                        ) : null}
                      </td>
                      <td className="whitespace-nowrap px-3 py-3 text-xs text-slate-600">
                        {formatDateTime(s.inventory_synced_at ?? s.last_checked_at)}
                      </td>
                      <td className="px-5 py-3">
                        <div className="flex flex-wrap justify-end gap-1.5">
                          <button type="button" className={btnSmall} disabled={pendingKey !== null}
                            onClick={() => doSync(s)}>
                            {isBusy(`sync:${s.id}`) ? "Queued…" : "Sync Now"}
                          </button>
                          <Link
                            href={`/pipelines/${pipelineId}?tab=inventory&source_id=${s.id}`}
                            className={btnSmall}
                          >
                            View Inventory
                          </Link>
                          <button type="button" className={btnSmall} disabled={pendingKey !== null}
                            onClick={() => doToggle(s)}>
                            {isBusy(`toggle:${s.id}`) ? "…" : s.enabled ? "Disable" : "Enable"}
                          </button>
                          <ConfirmButton
                            title="Xóa source?"
                            message={`Xóa "${s.name}"? Inventory của source này cũng bị xóa.`}
                            onConfirm={() => doDelete(s)}
                          />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {/* Mobile cards */}
            <div className="grid gap-3 p-4 md:hidden">
              {items.map((s) => (
                <div key={s.id} className="rounded-2xl border border-slate-200/90 bg-white p-3.5 shadow-[0_1px_2px_rgba(15,23,42,0.05)]">
                  <div className="flex items-start justify-between gap-2">
                    <p className="min-w-0 truncate font-bold text-slate-900">{s.name}</p>
                    {s.enabled ? <Badge tone="green" dot>On</Badge> : <Badge tone="slate" dot>Off</Badge>}
                  </div>
                  <p className="mt-1 break-all text-xs text-slate-500">{s.profile_url ?? "—"}</p>
                  <div className="mt-2 flex items-center gap-2 text-xs text-slate-500">
                    <SyncBadge status={s.inventory_sync_status} />
                    <span>· {formatDateTime(s.inventory_synced_at ?? s.last_checked_at)}</span>
                  </div>
                  {s.inventory_sync_status === "auth_required" ? (
                    <p className="mt-2">
                      <Badge tone="red">Douyin Login Required</Badge>
                    </p>
                  ) : null}
                  {typeof s.inventory_count === "number" ? (
                    <p className="mt-1 text-xs text-slate-600">Inventory: {s.inventory_count}</p>
                  ) : null}
                  {s.inventory_sync_error ? (
                    <p className="mt-1 break-words text-[11px] text-red-600">
                      {s.inventory_sync_error.slice(0, 200)}
                    </p>
                  ) : null}
                  <div className="mt-3 grid grid-cols-2 gap-1.5">
                    <button type="button" className={btnSmall} disabled={pendingKey !== null}
                      onClick={() => doSync(s)}>
                      {isBusy(`sync:${s.id}`) ? "Queued…" : "Sync Now"}
                    </button>
                    <Link href={`/pipelines/${pipelineId}?tab=inventory&source_id=${s.id}`} className={btnSmall}>
                      Inventory
                    </Link>
                    <button type="button" className={btnSmall} disabled={pendingKey !== null}
                      onClick={() => doToggle(s)}>
                      {isBusy(`toggle:${s.id}`) ? "…" : s.enabled ? "Disable" : "Enable"}
                    </button>
                    <ConfirmButton title="Xóa source?" message={`Xóa "${s.name}"?`} onConfirm={() => doDelete(s)} />
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </Card>
    </div>
  );
}

function SyncBadge({ status }: { status: string }) {
  if (status === "auth_required") return <Badge tone="red">auth_required</Badge>;
  const tone =
    status === "completed" ? "green" : status === "failed" ? "red" : status === "running" || status === "syncing" || status === "queued" ? "amber" : "slate";
  return <Badge tone={tone}>{status}</Badge>;
}

export function AddSourceButtonPlaceholder() {
  return <button type="button" className={btnSecondary}>Add</button>;
}
