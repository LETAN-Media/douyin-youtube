"use client";

import { useId, useState } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import { IconTrash } from "@/components/icons";
import { btnDanger, btnSecondary } from "@/components/ui";

type DeleteResponse = {
  error?: unknown;
  message?: unknown;
};

export function FacebookPipelineDeleteButton({
  pipelineId,
  name,
  onDeleted,
}: {
  pipelineId: string;
  name: string;
  onDeleted?: () => void;
}) {
  const router = useRouter();
  const titleId = useId();
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function close() {
    if (pending) return;
    setOpen(false);
    setError(null);
  }

  async function confirmDelete() {
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/facebook/pipelines/${encodeURIComponent(pipelineId)}`,
        { method: "DELETE" },
      );
      const data = (await res.json().catch(() => null)) as DeleteResponse | null;
      if (!res.ok) {
        const message =
          (typeof data?.error === "string" && data.error) ||
          (typeof data?.message === "string" && data.message) ||
          `HTTP ${res.status}`;
        throw new Error(message);
      }
      setOpen(false);
      onDeleted?.();
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không thể xoá pipeline.");
    } finally {
      setPending(false);
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          setError(null);
          setOpen(true);
        }}
        aria-label={`Xoá pipeline ${name}`}
        title="Xoá pipeline"
        className="pointer-events-auto inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-rose-200 bg-white text-rose-600 shadow-sm transition hover:border-rose-300 hover:bg-rose-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-400 focus-visible:ring-offset-2"
      >
        <IconTrash size={15} />
      </button>

      {open && typeof document !== "undefined"
        ? createPortal(
            <div
              className="fixed inset-0 z-[60] flex items-end justify-center bg-slate-900/50 p-4 backdrop-blur-[2px] sm:items-center"
              onClick={(event) => {
                if (event.target === event.currentTarget) close();
              }}
            >
              <div
                role="dialog"
                aria-modal="true"
                aria-labelledby={titleId}
                className="fade-up w-full max-w-sm rounded-3xl border border-slate-200 bg-white p-5 shadow-2xl"
              >
                <div className="flex items-start gap-3">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-rose-50 text-rose-600 ring-1 ring-inset ring-rose-200">
                    <IconTrash size={18} />
                  </span>
                  <div className="min-w-0">
                    <h3
                      id={titleId}
                      className="text-[15px] font-extrabold tracking-tight text-slate-900"
                    >
                      Xoá pipeline?
                    </h3>
                    <p className="mt-1 text-sm leading-relaxed text-slate-600">
                      Bạn có chắc muốn xoá{" "}
                      <span className="font-semibold text-slate-900">{name}</span>?
                    </p>
                  </div>
                </div>

                <p className="mt-3 rounded-xl bg-rose-50 px-3 py-2.5 text-xs leading-relaxed text-rose-700 ring-1 ring-inset ring-rose-100">
                  Toàn bộ Sources, Inventory, lịch đăng, queue và lịch sử của
                  pipeline này sẽ bị xoá. Không thể hoàn tác. Video đã đăng
                  trên YouTube sẽ không bị xoá.
                </p>

                {error ? (
                  <p
                    role="alert"
                    className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-2.5 text-xs font-medium text-rose-700"
                  >
                    {error}
                  </p>
                ) : null}

                <div className="mt-4 flex gap-2">
                  <button
                    type="button"
                    className={`${btnSecondary} flex-1`}
                    disabled={pending}
                    autoFocus
                    onClick={close}
                  >
                    Huỷ
                  </button>
                  <button
                    type="button"
                    className={`${btnDanger} flex-1`}
                    disabled={pending}
                    onClick={() => void confirmDelete()}
                  >
                    {pending ? "Đang xoá…" : "Đồng ý xoá"}
                  </button>
                </div>
              </div>
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
