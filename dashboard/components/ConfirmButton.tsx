"use client";

import { useState, useTransition } from "react";
import { useToast } from "./Toast";
import { btnDangerGhost, btnDanger, btnSecondary } from "./ui";
import type { ActionResult } from "@/lib/types";

export function ConfirmButton({
  title,
  message,
  confirmLabel = "Xóa",
  onConfirm,
}: {
  title: string;
  message: string;
  confirmLabel?: string;
  onConfirm: () => Promise<ActionResult>;
}) {
  const [open, setOpen] = useState(false);
  const [pending, start] = useTransition();
  const { toast } = useToast();

  return (
    <>
      <button
        type="button"
        className={btnDangerGhost}
        onClick={() => setOpen(true)}
        disabled={false}
      >
        {confirmLabel}
      </button>
      {open ? (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/50 p-4 backdrop-blur-[2px] sm:items-center">
          <div className="fade-up w-full max-w-sm rounded-3xl border border-slate-200 bg-white p-5 shadow-2xl">
            <h3 className="text-[15px] font-extrabold tracking-tight text-slate-900">{title}</h3>
            <p className="mt-1 text-sm leading-relaxed text-slate-600">{message}</p>
            <div className="mt-4 flex gap-2">
              <button
                type="button"
                className={`${btnSecondary} flex-1`}
                disabled={pending}
                onClick={() => setOpen(false)}
              >
                Hủy
              </button>
              <button
                type="button"
                className={`${btnDanger} flex-1`}
                disabled={pending}
                onClick={() =>
                  start(async () => {
                    const r = await onConfirm();
                    if (r.ok) {
                      toast("Đã xóa.", "success");
                      setOpen(false);
                    } else {
                      toast(r.error, "error");
                    }
                  })
                }
              >
                {pending ? "Đang xóa…" : confirmLabel}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
