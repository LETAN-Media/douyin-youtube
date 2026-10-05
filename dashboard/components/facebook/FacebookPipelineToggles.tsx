"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export const FACEBOOK_PIPELINE_UPDATED_EVENT = "facebook:pipeline-updated";

export type FacebookPipelineFlags = {
  enabled: boolean;
  auto_publish: boolean;
};

function badgeClass(on: boolean, accent: "emerald" | "indigo"): string {
  const base =
    "inline-flex min-h-[44px] items-center gap-2 rounded-full px-3.5 py-2 text-sm font-bold shadow-sm ring-1 ring-inset transition";
  if (on) {
    return accent === "emerald"
      ? `${base} bg-emerald-600 text-white ring-emerald-500`
      : `${base} bg-indigo-600 text-white ring-indigo-500`;
  }
  return `${base} bg-white text-slate-600 ring-slate-200`;
}

function dotClass(on: boolean): string {
  return `h-2.5 w-2.5 rounded-full ${on ? "bg-white" : "bg-slate-500"}`;
}

export function FacebookPipelineToggles({
  pipelineId,
  initialEnabled,
  initialAutoPublish,
}: {
  pipelineId: string;
  initialEnabled: boolean;
  initialAutoPublish: boolean;
}) {
  const router = useRouter();
  const [autoPublish, setAutoPublish] = useState(initialAutoPublish);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const enabled = initialEnabled;

  async function toggleAutoPublish() {
    if (pending) return;
    const next = !autoPublish;
    setPending(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/facebook/pipelines/${encodeURIComponent(pipelineId)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ auto_publish: next }),
        },
      );
      const data = (await res.json().catch(() => null)) as {
        auto_publish?: unknown;
        error?: unknown;
        message?: unknown;
      } | null;
      if (!res.ok) {
        const serverMessage =
          (typeof data?.error === "string" && data.error) ||
          (typeof data?.message === "string" && data.message) ||
          `HTTP ${res.status}`;
        throw new Error(serverMessage);
      }
      const confirmed =
        typeof data?.auto_publish === "boolean" ? data.auto_publish : next;
      setAutoPublish(confirmed);
      window.dispatchEvent(
        new CustomEvent<FacebookPipelineFlags>(FACEBOOK_PIPELINE_UPDATED_EVENT, {
          detail: { enabled, auto_publish: confirmed },
        }),
      );
      router.refresh();
    } catch (err) {
      // Rollback: keep the previous value, surface the error.
      setError(err instanceof Error ? err.message : "Không thể cập nhật Auto Publish.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1.5">
      <div className="flex items-center gap-2">
        <span className={badgeClass(enabled, "emerald")}>
          <span className={dotClass(enabled)} />
          Pipeline: {enabled ? "ON" : "OFF"}
        </span>
        <button
          type="button"
          onClick={toggleAutoPublish}
          disabled={pending}
          title={autoPublish ? "Tắt Auto Publish" : "Bật Auto Publish"}
          className={`${badgeClass(autoPublish, "indigo")} ${
            pending ? "cursor-wait opacity-70" : "cursor-pointer hover:brightness-95"
          } disabled:cursor-wait`}
        >
          <span className={dotClass(autoPublish)} />
          {pending ? "Đang lưu…" : `Auto Publish: ${autoPublish ? "ON" : "OFF"}`}
        </button>
      </div>
      {error ? (
        <p className="text-xs font-medium text-rose-600">{error}</p>
      ) : null}
    </div>
  );
}
