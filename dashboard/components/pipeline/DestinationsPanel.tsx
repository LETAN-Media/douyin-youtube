"use client";

import { useEffect, useState, useTransition } from "react";
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
  btnSmall,
  inputCls,
  labelCls,
} from "@/components/ui";
import {
  actionCreateDestination,
  actionDeleteDestination,
  actionGetOauthUrl,
  actionToggleDestination,
} from "@/lib/actions";
import { formatTime, platformLabel } from "@/lib/format";
import type { Destination, DestinationStatus } from "@/lib/types";
import { IconDestinations } from "@/components/icons";

export function DestinationsPanel({
  pipelineId,
  destinations,
  statusById,
  oauthSuccess,
}: {
  pipelineId: string;
  destinations: Destination[];
  statusById: Record<string, DestinationStatus | null>;
  oauthSuccess: boolean;
}) {
  const [showWizard, setShowWizard] = useState(false);
  const [items, setItems] = useState(destinations);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- refresh list on server data change
    setItems(destinations);
  }, [destinations]);
  const router = useRouter();
  const { toast } = useToast();
  const [, start] = useTransition();
  const [togglePendingId, setTogglePendingId] = useState<string | null>(null);

  const handleToggle = (id: string, next: boolean) => {
    if (togglePendingId) return;
    setTogglePendingId(id);
    setItems((prev) => prev.map((d) => (d.id === id ? { ...d, enabled: next } : d)));
    start(async () => {
      const r = await actionToggleDestination(pipelineId, id, next);
      setTogglePendingId(null);
      toast(r.ok ? (next ? "Đã resume." : "Đã pause.") : r.error, r.ok ? "success" : "error");
      if (!r.ok) {
        setItems((prev) => prev.map((d) => (d.id === id ? { ...d, enabled: !next } : d)));
      }
      router.refresh();
    });
  };

  const handleDelete = async (id: string) => {
    const r = await actionDeleteDestination(pipelineId, id);
    if (r.ok) {
      setItems((prev) => prev.filter((d) => d.id !== id));
      router.refresh();
    }
    return r;
  };

  const handleCreated = () => {
    setShowWizard(false);
    router.refresh();
  };

  const youtubes = items.filter((d) => d.platform === "youtube");
  const facebooks = items.filter((d) => d.platform === "facebook");

  return (
    <div className="space-y-4">
      {oauthSuccess ? (
        <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-medium text-emerald-900">
          YouTube đã kết nối. Trạng thái kênh hiển thị ở destination tương ứng.
        </div>
      ) : null}

      <Card>
        <CardHeader
          title={`Destinations (${items.length})`}
          subtitle="Schedule nằm ở từng destination. Mỗi destination có OAuth và lịch riêng."
          icon={<IconDestinations size={16} />}
          action={
            <button
              type="button"
              className={`${btnSmall} min-h-[44px]`}
              onClick={() => setShowWizard((v) => !v)}
            >
              + Add Destination
            </button>
          }
        />
        {showWizard ? (
          <DestinationWizard
            pipelineId={pipelineId}
            onDone={handleCreated}
          />
        ) : null}

        {items.length === 0 ? (
          <EmptyState
            title="Chưa có destination"
            hint="Thêm YouTube destination đầu tiên, sau đó Connect OAuth bằng destination_id."
          />
        ) : (
          <div className="space-y-5 p-4 sm:px-5">
            <PlatformGroup
              title="YouTube"
              pipelineId={pipelineId}
              items={youtubes}
              statusById={statusById}
              togglePendingId={togglePendingId}
              onToggle={handleToggle}
              onDelete={handleDelete}
            />
            <PlatformGroup
              title="Facebook"
              pipelineId={pipelineId}
              items={facebooks}
              statusById={statusById}
              togglePendingId={togglePendingId}
              onToggle={handleToggle}
              onDelete={handleDelete}
            />
          </div>
        )}
      </Card>
    </div>
  );
}

function PlatformGroup({
  title,
  pipelineId,
  items,
  statusById,
  togglePendingId,
  onToggle,
  onDelete,
}: {
  title: string;
  pipelineId: string;
  items: Destination[];
  statusById: Record<string, DestinationStatus | null>;
  togglePendingId: string | null;
  onToggle: (id: string, next: boolean) => void;
  onDelete: (id: string) => Promise<{ ok: true } | { ok: false; error: string }>;
}) {
  if (items.length === 0) return null;
  return (
    <section>
      <h3 className="text-xs font-bold uppercase tracking-wide text-slate-500">
        {title} ({items.length})
      </h3>
      <div className="mt-2 grid gap-3 sm:grid-cols-2">
        {items.map((d) => (
          <DestinationCard
            key={d.id}
            pipelineId={pipelineId}
            destination={d}
            status={statusById[d.id] ?? null}
            togglePending={togglePendingId === d.id}
            onToggle={onToggle}
            onDelete={onDelete}
          />
        ))}
      </div>
    </section>
  );
}

export function DestinationCard({
  pipelineId,
  destination: d,
  status,
  togglePending = false,
  onToggle,
  onDelete,
}: {
  pipelineId: string;
  destination: Destination;
  status: DestinationStatus | null;
  togglePending?: boolean;
  onToggle?: (id: string, next: boolean) => void;
  onDelete?: (id: string) => Promise<{ ok: true } | { ok: false; error: string }>;
}) {
  const { toast } = useToast();
  const router = useRouter();
  const [pending, start] = useTransition();
  const isFacebook = d.platform === "facebook";
  const connected = isFacebook ? false : (status?.connected ?? d.connected);
  const todayCount = status?.today_published ?? 0;
  const next = status?.next_upload ?? null;

  const connect = () =>
    start(async () => {
      if (isFacebook) {
        toast("Facebook publishing adapter not configured", "error");
        return;
      }
      const r = await actionGetOauthUrl(d.id);
      if (r.ok && r.url) {
        window.location.href = r.url;
      } else {
        toast(r.ok ? "Không lấy được OAuth URL." : r.error, "error");
      }
    });

  const doToggleFallback = () =>
    start(async () => {
      const { actionToggleDestination: toggle } = await import("@/lib/actions");
      const r = await toggle(pipelineId, d.id, !d.enabled);
      toast(r.ok ? (d.enabled ? "Đã pause." : "Đã resume.") : r.error, r.ok ? "success" : "error");
      if (r.ok) router.refresh();
    });

  return (
    <div className={`flex flex-col rounded-2xl border p-4 shadow-[0_1px_2px_rgba(15,23,42,0.05)] transition hover:border-indigo-200 hover:shadow-md ${d.enabled ? "border-slate-200/90 bg-white" : "border-amber-200 bg-amber-50/40"}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-sm font-black text-white ${isFacebook ? "bg-gradient-to-br from-sky-500 to-blue-600" : "bg-gradient-to-br from-rose-500 to-red-600"}`}>
            {d.name.slice(0, 1).toUpperCase()}
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-extrabold text-slate-900">{d.name}</p>
            <p className="text-xs text-slate-500">{platformLabel(d.platform)} · {d.daily_upload_limit}/day</p>
          </div>
        </div>
        {connected ? (
          <Badge tone="green" dot>Connected</Badge>
        ) : (
          <Badge tone="slate" dot>Not Connected</Badge>
        )}
      </div>

      {isFacebook ? (
        <p className="mt-2 rounded-lg bg-amber-50 px-2.5 py-2 text-xs font-medium text-amber-800">
          Facebook publishing adapter not configured
        </p>
      ) : (
        <p className="mt-2 text-xs text-slate-600">
          {d.external_account_name ? (
            <>Kênh: <span className="font-semibold">{d.external_account_name}</span></>
          ) : (
            <>Chưa kết nối kênh</>
          )}
          <br />
          Today {todayCount}/{d.daily_upload_limit} · Next: {next ? formatTime(next) : "—"}
        </p>
      )}

      {/* Schedule slots */}
      <div className="mt-2 flex flex-wrap gap-1">
        {(d.upload_slots ?? []).map((s) => (
          <span key={s} className="rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-700">
            {s}
          </span>
        ))}
        <span className="rounded-md bg-slate-50 px-1.5 py-0.5 text-[11px] text-slate-500">
          {d.timezone}
        </span>
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        <Link
          href={`/pipelines/${pipelineId}/destinations/${d.id}`}
          className={btnSmall}
        >
          Detail
        </Link>
        {!isFacebook ? (
          <button type="button" className={btnSmall} disabled={pending} onClick={connect}>
            {pending ? "…" : connected ? "Reconnect" : "Connect"}
          </button>
        ) : null}
        {onToggle ? (
          <button
            type="button"
            className={btnSmall}
            disabled={togglePending}
            onClick={() => onToggle(d.id, !d.enabled)}
          >
            {togglePending ? "…" : d.enabled ? "Pause" : "Resume"}
          </button>
        ) : (
          <DestinationPauseButton pipelineId={pipelineId} id={d.id} enabled={d.enabled} />
        )}
        <ConfirmButton
          title="Xóa destination?"
          message={`Xóa "${d.name}"? Publications của destination này cũng bị xóa.`}
          onConfirm={() =>
            onDelete ? onDelete(d.id) : actionDeleteDestination(pipelineId, d.id)
          }
        />
      </div>
      {!d.enabled ? (
        <p className="mt-2 text-xs font-semibold text-amber-700">Paused</p>
      ) : null}
    </div>
  );
}

function DestinationPauseButton({
  pipelineId,
  id,
  enabled,
}: {
  pipelineId: string;
  id: string;
  enabled: boolean;
}) {
  const { toast } = useToast();
  const router = useRouter();
  const [pending, start] = useTransition();
  const [optimistic, setOptimistic] = useState(enabled);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- sync prop after transition settles
    if (!pending) setOptimistic(enabled);
  }, [enabled, pending]);
  return (
    <button
      type="button"
      className={btnSmall}
      disabled={pending}
      onClick={() =>
        start(async () => {
          const next = !optimistic;
          setOptimistic(next);
          const r = await actionToggleDestination(pipelineId, id, next);
          toast(r.ok ? (next ? "Đã resume." : "Đã pause.") : r.error, r.ok ? "success" : "error");
          if (!r.ok) setOptimistic(!next);
          else router.refresh();
        })
      }
    >
      {pending ? "…" : optimistic ? "Pause" : "Resume"}
    </button>
  );
}

function DestinationWizard({
  pipelineId,
  onDone,
}: {
  pipelineId: string;
  onDone: () => void;
}) {
  const { toast } = useToast();
  const [pending, start] = useTransition();

  return (
    <form
      className="space-y-3 border-b border-slate-100 p-4 sm:px-5"
      onSubmit={(e) => {
        e.preventDefault();
        if (pending) return;
        const form = new FormData(e.currentTarget);
        start(async () => {
          const r = await actionCreateDestination(pipelineId, form);
          if (!r.ok) {
            toast(r.error, "error");
            return;
          }
          toast("Đã tạo destination.", "success");
          onDone();
          if (r.oauthUrl) {
            window.location.href = r.oauthUrl;
          }
        });
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className={labelCls} htmlFor="w-platform">Platform</label>
          <select id="w-platform" name="platform" defaultValue="youtube" className={inputCls}>
            <option value="youtube">YouTube</option>
            <option value="facebook">Facebook</option>
          </select>
        </div>
        <div>
          <label className={labelCls} htmlFor="w-name">Name</label>
          <input id="w-name" name="name" required placeholder="YouTube A" className={inputCls} />
        </div>
        <div>
          <label className={labelCls} htmlFor="w-strategy">Publish strategy</label>
          <select id="w-strategy" name="publish_strategy" defaultValue="broadcast" className={inputCls}>
            <option value="broadcast">broadcast</option>
            <option value="rotate">rotate</option>
            <option value="selected">selected</option>
          </select>
        </div>
        <div>
          <label className={labelCls} htmlFor="w-limit">Daily upload limit</label>
          <input id="w-limit" name="daily_upload_limit" type="number" min={1} max={50} defaultValue={6} className={inputCls} />
        </div>
        <div>
          <label className={labelCls} htmlFor="w-tz">Timezone</label>
          <input id="w-tz" name="timezone" defaultValue="Asia/Ho_Chi_Minh" className={inputCls} />
        </div>
        <div>
          <label className={labelCls} htmlFor="w-slots">Upload slots</label>
          <input id="w-slots" name="upload_slots" defaultValue="08:00,11:00,14:00,17:00,20:00,23:00" className={inputCls} />
        </div>
        <div>
          <label className={labelCls} htmlFor="w-lang">Metadata language</label>
          <input id="w-lang" name="metadata_language" placeholder="en" className={inputCls} />
        </div>
        <div>
          <label className={labelCls} htmlFor="w-profile">Metadata profile</label>
          <input id="w-profile" name="metadata_profile" placeholder="default" className={inputCls} />
        </div>
      </div>
      <p className="text-xs text-slate-500">
        Nếu YouTube: sau khi tạo sẽ tự chuyển sang Connect YouTube OAuth bằng destination_id.
      </p>
      <div className="flex gap-2">
        <button type="button" className="inline-flex min-h-[44px] flex-1 items-center justify-center rounded-xl border border-slate-200 px-3.5 py-2 text-sm font-semibold text-slate-700" onClick={onDone}>
          Hủy
        </button>
        <button type="submit" disabled={pending} className={`${btnPrimary} min-h-[44px] flex-1`}>
          {pending ? "Đang tạo…" : "Create"}
        </button>
      </div>
    </form>
  );
}
