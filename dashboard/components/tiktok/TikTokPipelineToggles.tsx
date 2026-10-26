"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export const TIKTOK_PIPELINE_UPDATED_EVENT = "tiktok:pipeline-updated";

export type TikTokPipelineFlags = {
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

export function useTikTokAutoPublishToggle({
  pipelineId,
  initialAutoPublish,
  enabled,
}: {
  pipelineId: string;
  initialAutoPublish: boolean;
  enabled: boolean;
}) {
  const router = useRouter();
  const [autoPublishOverride, setAutoPublishOverride] = useState<boolean | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const autoPublish = autoPublishOverride ?? initialAutoPublish;

  async function toggleAutoPublish() {
    if (pending) return;
    const next = !autoPublish;
    setPending(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/tiktok/pipelines/${encodeURIComponent(pipelineId)}/auto_publish`,
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
      setAutoPublishOverride(confirmed);
      window.dispatchEvent(
        new CustomEvent<TikTokPipelineFlags>(TIKTOK_PIPELINE_UPDATED_EVENT, {
          detail: { enabled, auto_publish: confirmed },
        }),
      );
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không thể cập nhật Auto Publish.");
    } finally {
      setPending(false);
    }
  }

  return { autoPublish, pending, error, toggleAutoPublish };
}

export function TikTokPipelineToggles({
  pipelineId,
  initialEnabled,
  initialAutoPublish,
}: {
  pipelineId: string;
  initialEnabled: boolean;
  initialAutoPublish: boolean;
}) {
  const { autoPublish, pending, error, toggleAutoPublish } =
    useTikTokAutoPublishToggle({ pipelineId, initialAutoPublish, enabled: initialEnabled });

  return (
    <div className="flex flex-col items-end gap-1.5">
      <div className="flex items-center gap-2">
        <span className={badgeClass(initialEnabled, "emerald")}>
          <span className={dotClass(initialEnabled)} />
          Pipeline: {initialEnabled ? "ON" : "OFF"}
        </span>
        <button
          type="button"
          onClick={toggleAutoPublish}
          disabled={pending}
          aria-busy={pending}
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

export function TikTokPipelineAutoToggle({
  pipelineId,
  initialAutoPublish,
  enabled,
  className = "",
}: {
  pipelineId: string;
  initialAutoPublish: boolean;
  enabled: boolean;
  className?: string;
}) {
  const { autoPublish, pending, error, toggleAutoPublish } =
    useTikTokAutoPublishToggle({ pipelineId, initialAutoPublish, enabled });

  return (
    <div
      className={`flex shrink-0 flex-col items-end gap-1 ${className}`}
      onClick={(event) => event.stopPropagation()}
    >
      <button
        type="button"
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          void toggleAutoPublish();
        }}
        aria-busy={pending}
        aria-disabled={pending}
        aria-pressed={autoPublish}
        aria-label={autoPublish ? "Tắt đăng tự động" : "Bật đăng tự động"}
        title={autoPublish ? "Tắt Auto Publish" : "Bật Auto Publish"}
        className={`pointer-events-auto inline-flex min-h-[36px] items-center gap-1.5 rounded-full px-2.5 py-1.5 text-[11px] font-bold shadow-sm ring-1 ring-inset transition ${
          autoPublish
            ? "bg-emerald-600 text-white ring-emerald-500 hover:bg-emerald-700"
            : "bg-slate-100 text-slate-600 ring-slate-300 hover:bg-slate-200"
        } ${pending ? "cursor-wait opacity-70" : "cursor-pointer"}`}
      >
        {pending ? (
          <span
            aria-hidden="true"
            className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"
          />
        ) : (
          <span
            aria-hidden="true"
            className={`h-1.5 w-1.5 rounded-full ${
              autoPublish ? "bg-white" : "bg-slate-500"
            }`}
          />
        )}
        {pending ? "Đang lưu…" : autoPublish ? "AUTO ON" : "AUTO OFF"}
      </button>
      {error ? (
        <p className="max-w-[190px] text-right text-[11px] font-medium leading-tight text-rose-600">
          {error}
        </p>
      ) : null}
    </div>
  );
}
