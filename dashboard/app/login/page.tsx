"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();

  return (
    <div className="flex min-h-dvh items-center justify-center px-4">
      <div className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-600 text-base font-black text-white">
          D
        </div>
        <h1 className="mt-4 text-lg font-bold text-slate-900">
          Douyin Control Panel
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          Đăng nhập admin để quản lý pipelines.
        </p>
        {error ? (
          <p className="mt-3 rounded-xl bg-red-50 px-3 py-2 text-sm font-medium text-red-700">
            {error}
          </p>
        ) : null}
        <form
          className="mt-4 space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
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
              className="mb-1 block text-xs font-semibold text-slate-600"
            >
              Mật khẩu admin (DASHBOARD_SECRET)
            </label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              className="w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
            />
          </div>
          <button
            type="submit"
            disabled={pending}
            className="w-full rounded-xl bg-indigo-600 px-3.5 py-2.5 text-sm font-semibold text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            {pending ? "Đang đăng nhập…" : "Đăng nhập"}
          </button>
        </form>
      </div>
    </div>
  );
}
