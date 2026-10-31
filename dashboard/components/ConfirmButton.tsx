"use client";

import { useState, useTransition } from "react";
import { useToast } from "./Toast";
import { btnDangerGhost, btnDanger, btnSecondary, inputCls, labelCls } from "./ui";
import type { ActionResult } from "@/lib/types";

// Compare the typed confirmation loosely: case, surrounding/extra spaces and
// Unicode composition must never block a destructive action the user clearly
// intends (e.g. pipeline "TC Media" typed as "tc media").
function normalizeConfirmation(value: string): string {
  return value.normalize("NFC").trim().replace(/\s+/g, " ").toLowerCase();
}

/**
 * Destructive-action confirmation.
 *
 * - `requireText`: the user must type this exact value (e.g. pipeline name)
 *   before the destructive button unlocks.
 * - `details`: extra consequence text shown under the message.
 * - The button is locked while the request runs so double clicks cannot send
 *   two deletes, and failures are shown inline (with the backend's specific
 *   reason) instead of a bare error page.
 */
export function ConfirmButton({
  title,
  message,
  details,
  requireText,
  confirmLabel = "Xóa",
  onConfirm,
}: {
  title: string;
  message: string;
  details?: string;
  requireText?: string;
  confirmLabel?: string;
  onConfirm: () => Promise<ActionResult>;
}) {
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const { toast } = useToast();

  const matches =
    !requireText ||
    normalizeConfirmation(typed) === normalizeConfirmation(requireText);

  const close = () => {
    if (pending) return;
    setOpen(false);
    setTyped("");
    setError(null);
  };

  const confirm = () => {
    if (pending || !matches) return;
    setError(null);
    start(async () => {
      const r = await onConfirm();
      if (r.ok) {
        toast("Đã xóa.", "success");
        setOpen(false);
        setTyped("");
      } else {
        setError(r.error);
        toast(r.error, "error");
      }
    });
  };

  return (
    <>
      <button
        type="button"
        className={btnDangerGhost}
        onClick={() => {
          setTyped("");
          setError(null);
          setOpen(true);
        }}
        disabled={false}
      >
        {confirmLabel}
      </button>
      {open ? (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/50 p-4 backdrop-blur-[2px] sm:items-center">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="confirm-title"
            className="fade-up max-h-[92dvh] w-full max-w-sm overflow-y-auto rounded-3xl border border-slate-200 bg-white p-5 shadow-2xl"
          >
            <h3
              id="confirm-title"
              className="text-[15px] font-extrabold tracking-tight text-slate-900"
            >
              {title}
            </h3>
            <p className="mt-1 text-sm leading-relaxed text-slate-600">{message}</p>
            {details ? (
              <p className="mt-1 text-xs leading-relaxed text-slate-500">{details}</p>
            ) : null}

            {requireText ? (
              <label className={`${labelCls} mt-3`} htmlFor="confirm-text">
                Nhập <span className="font-mono font-bold text-slate-900">{requireText}</span> để xác nhận
                <input
                  id="confirm-text"
                  value={typed}
                  onChange={(event) => {
                    setTyped(event.target.value);
                    setError(null);
                  }}
                  autoComplete="off"
                  autoCapitalize="off"
                  spellCheck={false}
                  disabled={pending}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      confirm();
                    }
                  }}
                  className={`${inputCls} mt-1`}
                />
                {typed.length > 0 && !matches ? (
                  <span className="mt-1 block text-[11px] font-normal text-amber-700">
                    Tên chưa khớp (không phân biệt hoa/thường).
                  </span>
                ) : null}
              </label>
            ) : null}

            {error ? (
              <p
                role="alert"
                className="mt-3 rounded-xl bg-rose-50 p-3 text-xs leading-relaxed text-rose-700"
              >
                {error}
              </p>
            ) : null}

            <div className="mt-4 flex gap-2">
              <button
                type="button"
                className={`${btnSecondary} flex-1`}
                disabled={pending}
                onClick={close}
              >
                Hủy
              </button>
              <button
                type="button"
                className={`${btnDanger} flex-1`}
                disabled={pending || !matches}
                onClick={confirm}
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
