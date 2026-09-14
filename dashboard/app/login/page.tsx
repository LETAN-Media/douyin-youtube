"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Spinner } from "@/components/ui";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();

  return (
    <div className="relative flex min-h-dvh items-center justify-center overflow-hidden px-4">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(800px_400px_at_50%_-80px,rgba(99,102,241,0.22),transparent_65%),radial-gradient(600px_320px_at_90%_110%,rgba(16,185,129,0.14),transparent_60%)]"
      />
      <div className="fade-up relative w-full max-w-sm rounded-3xl border border-white/60 bg-white/90 p-7 shadow-[0_24px_60px_-24px_rgba(15,23,42,0.35)] backdrop-blur">
        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-600 text-xl font-black text-white shadow-[0_8px_20px_-6px_rgba(79,70,229,0.7)]">
          D
        </div>
        <h1 className="mt-4 text-xl font-extrabold tracking-tight text-slate-900">
          Douyin Control Panel
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          Đăng nhập admin để quản lý pipelines.
        </p>
        {error ? (
          <p className="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-3.5 py-2.5 text-sm font-semibold text-rose-700">
            {error}
          </p>
        ) : null}
        <form
          className="mt-5 space-y-3.5"
          onSubmit={(e) => {
            e.preventDefault();
            if (pending) return;
            setError(null);
            const form = new FormData(e.currentTarget);
            start(async () => {
              try {
                const res = await fetch("/api/auth/login", {
                  method: "POST",
                  body: form,
                });
                if (res.ok) {
                  router.push("/");
                  router.refresh();
                } else {
                  const data = await res.json().catch(() => null);
                  setError(data?.error ?? "Đăng nhập thất bại.");
                }
              } catch {
                setError("Không kết nối được server.");
              }
            });
          }}
        >
          <div>
            <label
              htmlFor="password"
              className="mb-1.5 block text-xs font-bold text-slate-600"
            >
              Mật khẩu admin (DASHBOARD_SECRET)
            </label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              className="w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm shadow-sm outline-none transition placeholder:text-slate-400 hover:border-slate-300 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100"
            />
          </div>
          <button
            type="submit"
            disabled={pending}
            className="inline-flex min-h-[44px] w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 px-3.5 py-2.5 text-sm font-bold text-white shadow-[0_8px_20px_-8px_rgba(79,70,229,0.8)] transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {pending ? <Spinner size={15} /> : null}
            {pending ? "Đang đăng nhập…" : "Đăng nhập"}
          </button>
        </form>
        <p className="mt-5 text-center text-[11px] text-slate-400">
          Pipeline → Sources → Inventory → Destinations → Publications
        </p>
      </div>
    </div>
  );
}
