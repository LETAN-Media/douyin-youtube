"use client";

import { useTransition } from "react";
import { useToast } from "@/components/Toast";
import { actionTogglePipeline } from "@/lib/actions";

export function PipelineToggle({
  id,
  enabled,
}: {
  id: string;
  enabled: boolean;
}) {
  const [pending, start] = useTransition();
  const { toast } = useToast();

  return (
    <button
      type="button"
      disabled={pending}
      onClick={() =>
        start(async () => {
          const r = await actionTogglePipeline(id, !enabled);
          toast(
            r.ok ? (enabled ? "Đã tắt AUTO." : "Đã bật AUTO.") : r.error,
            r.ok ? "success" : "error",
          );
        })
      }
      className={`inline-flex items-center gap-2 rounded-xl px-3.5 py-2 text-sm font-semibold shadow-sm transition disabled:opacity-50 ${
        enabled
          ? "bg-emerald-600 text-white hover:bg-emerald-500"
          : "bg-slate-200 text-slate-700 hover:bg-slate-300"
      }`}
    >
      <span
        aria-hidden
        className={`inline-block h-2.5 w-2.5 rounded-full ${enabled ? "bg-white" : "bg-slate-500"}`}
      />
      {pending ? "…" : enabled ? "AUTO ON" : "AUTO OFF"}
    </button>
  );
}
