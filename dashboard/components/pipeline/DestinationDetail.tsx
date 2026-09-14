"use client";

import { useTransition } from "react";
import { useToast } from "@/components/Toast";
import { ConfirmButton } from "@/components/ConfirmButton";
import { Card, CardHeader, btnPrimary, btnSmall, inputCls, labelCls } from "@/components/ui";
import {
  actionDeleteDestination,
  actionGetOauthUrl,
  actionToggleDestination,
  actionUpdateDestination,
} from "@/lib/actions";
import type { Destination } from "@/lib/types";
import { useRouter } from "next/navigation";

export function DestinationActions({
  pipelineId,
  destination,
  isFacebook,
  connected,
}: {
  pipelineId: string;
  destination: Destination;
  isFacebook: boolean;
  connected: boolean;
}) {
  const { toast } = useToast();
  const [pending, start] = useTransition();
  const router = useRouter();

  return (
    <div className="flex flex-wrap gap-1.5">
      {!isFacebook ? (
        <button
          type="button"
          className={btnSmall}
          disabled={pending}
          onClick={() =>
            start(async () => {
              const r = await actionGetOauthUrl(destination.id);
              if (r.ok && r.url) window.location.href = r.url;
              else toast(r.ok ? "Lỗi." : r.error, "error");
            })
          }
        >
          {pending ? "…" : connected ? "Reconnect" : "Connect"}
        </button>
      ) : null}
      <button
        type="button"
        className={btnSmall}
        disabled={pending}
        onClick={() => {
          if (pending) return;
          start(async () => {
            const r = await actionToggleDestination(pipelineId, destination.id, !destination.enabled);
            toast(r.ok ? (destination.enabled ? "Đã pause." : "Đã resume.") : r.error, r.ok ? "success" : "error");
            if (r.ok) router.refresh();
          });
        }}
      >
        {pending ? "…" : destination.enabled ? "Pause" : "Resume"}
      </button>
      <ConfirmButton
        title="Xóa destination?"
        message={`Xóa "${destination.name}"?`}
        onConfirm={async () => {
          const r = await actionDeleteDestination(pipelineId, destination.id);
          if (r.ok) router.push(`/pipelines/${pipelineId}?tab=destinations`);
          return r;
        }}
      />
    </div>
  );
}

export function DestinationEditForm({
  pipelineId,
  destination,
}: {
  pipelineId: string;
  destination: Destination;
}) {
  const { toast } = useToast();
  const [pending, start] = useTransition();
  const router = useRouter();

  return (
    <Card>
      <CardHeader title="Edit destination" subtitle="Schedule riêng của destination này" />
      <form
        className="grid gap-3 p-4 sm:grid-cols-2 sm:px-5"
        onSubmit={(e) => {
          e.preventDefault();
          if (pending) return;
          const form = new FormData(e.currentTarget);
          start(async () => {
            const r = await actionUpdateDestination(pipelineId, destination.id, form);
            toast(r.ok ? "Đã lưu." : r.error, r.ok ? "success" : "error");
            if (r.ok) router.refresh();
          });
        }}
      >
        <div>
          <label className={labelCls}>Name</label>
          <input name="name" defaultValue={destination.name} className={inputCls} />
        </div>
        <div>
          <label className={labelCls}>Daily upload limit</label>
          <input name="daily_upload_limit" type="number" min={1} max={50} defaultValue={destination.daily_upload_limit} className={inputCls} />
        </div>
        <div>
          <label className={labelCls}>Timezone</label>
          <input name="timezone" defaultValue={destination.timezone} className={inputCls} />
        </div>
        <div>
          <label className={labelCls}>Upload slots</label>
          <input name="upload_slots" defaultValue={(destination.upload_slots ?? []).join(",")} className={inputCls} />
        </div>
        <div>
          <label className={labelCls}>Publish strategy</label>
          <select name="publish_strategy" defaultValue={destination.publish_strategy} className={inputCls}>
            <option value="broadcast">broadcast</option>
            <option value="rotate">rotate</option>
            <option value="selected">selected</option>
          </select>
        </div>
        <div>
          <label className={labelCls}>Metadata language</label>
          <input name="metadata_language" defaultValue={destination.metadata_language ?? ""} className={inputCls} />
        </div>
        <div className="sm:col-span-2">
          <label className={labelCls}>Metadata profile</label>
          <input name="metadata_profile" defaultValue={destination.metadata_profile ?? ""} className={inputCls} />
        </div>
        <div className="sm:col-span-2">
          <button type="submit" disabled={pending} className={btnPrimary}>
            {pending ? "Đang lưu…" : "Save"}
          </button>
        </div>
      </form>
    </Card>
  );
}
