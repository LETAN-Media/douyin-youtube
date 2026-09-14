"use client";

import { useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
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
  const router = useRouter();
  // Optimistic: flip immediately on tap, revert on failure.
  const [optimistic, setOptimistic] = useState(enabled);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- sync prop after transition settles
    if (!pending) setOptimistic(enabled);
  }, [enabled, pending]);

  return (
    <button
      type="button"
      disabled={pending}
      aria-pressed={optimistic}
      onClick={() =>
        start(async () => {
          const next = !optimistic;
          setOptimistic(next);
          const r = await actionTogglePipeline(id, next);
          if (r.ok) {
            toast(next ? "Đã bật AUTO." : "Đã tắt AUTO.", "success");
            // Targeted refresh: only current tab refetches (1-3 requests).
            router.refresh();
          } else {
            setOptimistic(!next);
            toast(r.error, "error");
          }
        })
      }
      className={`inline-flex min-h-[44px] items-center gap-2 rounded-full py-2 pl-3.5 pr-4 text-sm font-bold shadow-sm ring-1 ring-inset transition disabled:cursor-not-allowed disabled:opacity-50 ${
        optimistic
          ? "bg-emerald-600 text-white ring-emerald-500 hover:bg-emerald-500"
          : "bg-white text-slate-600 ring-slate-200 hover:bg-slate-50 hover:text-slate-900"
      }`}
    >
      <span
        aria-hidden
        className={`inline-block h-2.5 w-2.5 rounded-full ${optimistic ? "bg-white" : "bg-slate-500"}`}
      />
      {pending ? (
        <span aria-hidden className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />
      ) : null}
      {pending ? "…" : optimistic ? "AUTO ON" : "AUTO OFF"}
    </button>
  );
}
