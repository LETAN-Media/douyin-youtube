"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export function FacebookPipelineRename({
  pipelineId,
  initialName,
}: {
  pipelineId: string;
  initialName: string;
}) {
  const router = useRouter();
  const [name, setName] = useState(initialName);
  const [draft, setDraft] = useState(initialName);
  const [editing, setEditing] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function startEdit() {
    setDraft(name);
    setError(null);
    setEditing(true);
  }

  async function save() {
    const clean = draft.trim();
    if (!clean || pending) return;
    if (clean === name) {
      setEditing(false);
      return;
    }
    setPending(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/facebook/pipelines/${encodeURIComponent(pipelineId)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: clean }),
        },
      );
      const data = (await res.json().catch(() => null)) as {
        name?: unknown;
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
      // Rollback guard: keep the old name unless the backend confirms.
      if (typeof data?.name !== "string" || !data.name.trim()) {
        throw new Error("Backend không trả về tên mới.");
      }
      setName(data.name.trim());
      setEditing(false);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không thể đổi tên pipeline.");
    } finally {
      setPending(false);
    }
  }

  if (!editing) {
    return (
      <div className="flex flex-col gap-1">
        <div className="flex min-w-0 items-center gap-2">
          <h1 className="truncate text-xl font-extrabold tracking-tight text-slate-900 sm:text-2xl">
            {name}
          </h1>
          <button
            type="button"
            onClick={startEdit}
            title="Đổi tên pipeline"
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-slate-200 bg-white text-xs font-bold text-slate-500 shadow-sm transition hover:bg-slate-50 hover:text-slate-700"
          >
            ✎
          </button>
        </div>
        {error ? (
          <p className="text-xs font-medium text-rose-600">{error}</p>
        ) : null}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex min-w-0 items-center gap-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void save();
            if (e.key === "Escape") setEditing(false);
          }}
          disabled={pending}
          maxLength={200}
          autoFocus
          className="min-w-0 flex-1 rounded-xl border border-indigo-300 bg-white px-3 py-2 text-xl font-extrabold tracking-tight text-slate-900 shadow-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-200 sm:text-2xl"
        />
        <button
          type="button"
          onClick={() => void save()}
          disabled={pending || !draft.trim()}
          className="inline-flex min-h-[44px] shrink-0 items-center rounded-xl bg-indigo-600 px-3.5 py-2 text-xs font-bold text-white shadow-sm transition hover:bg-indigo-500 disabled:cursor-wait disabled:opacity-70"
        >
          {pending ? "Đang lưu…" : "Lưu"}
        </button>
        <button
          type="button"
          onClick={() => setEditing(false)}
          disabled={pending}
          className="inline-flex min-h-[44px] shrink-0 items-center rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50"
        >
          Hủy
        </button>
      </div>
      {error ? (
        <p className="text-xs font-medium text-rose-600">{error}</p>
      ) : null}
    </div>
  );
}
