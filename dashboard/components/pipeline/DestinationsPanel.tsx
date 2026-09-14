"use client";

import { useState, useTransition } from "react";
import Link from "next/link";
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
  const youtubes = destinations.filter((d) => d.platform === "youtube");
  const facebooks = destinations.filter((d) => d.platform === "facebook");

  return (
    <div className="space-y-4">
      {oauthSuccess ? (
        <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-medium text-emerald-900">
          YouTube đã kết nối. Trạng thái kênh hiển thị ở destination tương ứng.
        </div>
      ) : null}

      <Card>
        <CardHeader
          title={`Destinations (${destinations.length})`}
          subtitle="Schedule nằm ở từng destination. Mỗi destination có OAuth và lịch riêng."
          action={
            <button type="button" className={btnSmall} onClick={() => setShowWizard((v) => !v)}>
              + Add Destination
            </button>
          }
        />
        {showWizard ? (
          <DestinationWizard
            pipelineId={pipelineId}
            onDone={() => setShowWizard(false)}
          />
        ) : null}

        {destinations.length === 0 ? (
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
            />
            <PlatformGroup
              title="Facebook"
              pipelineId={pipelineId}
              items={facebooks}
              statusById={statusById}
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
}: {
  title: string;
  pipelineId: string;
  items: Destination[];
  statusById: Record<string, DestinationStatus | null>;
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
}: {
  pipelineId: string;
  destination: Destination;
  status: DestinationStatus | null;
}) {
  const { toast } = useToast();
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

  return (
    <div className="flex flex-col rounded-xl border border-slate-200 p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-bold text-slate-900">{d.name}</p>
          <p className="text-xs text-slate-500">{platformLabel(d.platform)} · {d.daily_upload_limit}/day</p>
        </div>
        {connected ? (
          <Badge tone="green">Connected</Badge>
        ) : (
          <Badge tone="slate">Not Connected</Badge>
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
        <DestinationPauseButton pipelineId={pipelineId} id={d.id} enabled={d.enabled} />
        <ConfirmButton
          title="Xóa destination?"
          message={`Xóa "${d.name}"? Publications của destination này cũng bị xóa.`}
          onConfirm={() => actionDeleteDestination(pipelineId, d.id)}
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
  const [pending, start] = useTransition();
  return (
    <button
      type="button"
      className={btnSmall}
      disabled={pending}
      onClick={() =>
        start(async () => {
          const r = await actionToggleDestination(pipelineId, id, !enabled);
          toast(r.ok ? (enabled ? "Đã pause." : "Đã resume.") : r.error, r.ok ? "success" : "error");
        })
      }
    >
      {enabled ? "Pause" : "Resume"}
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
        <button type="button" className="flex-1 rounded-xl border border-slate-200 px-3.5 py-2 text-sm font-semibold text-slate-700" onClick={onDone}>
          Hủy
        </button>
        <button type="submit" disabled={pending} className={`${btnPrimary} flex-1`}>
          {pending ? "Đang tạo…" : "Create"}
        </button>
      </div>
    </form>
  );
}
