"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";

const nav = [
  { href: "/", label: "Dashboard", icon: "◧" },
];

function LogoutButton() {
  const router = useRouter();
  return (
    <button
      type="button"
      className="rounded-xl border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50"
      onClick={async () => {
        try {
          await fetch("/api/auth/logout", { method: "POST" });
        } finally {
          router.push("/login");
          router.refresh();
        }
      }}
    >
      Đăng xuất
    </button>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  return (
    <div className="min-h-dvh">
      {/* Topbar */}
      <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-3 px-4 sm:px-6">
          <button
            type="button"
            aria-label="Mở menu"
            onClick={() => setOpen(true)}
            className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-slate-200 text-slate-700 lg:hidden"
          >
            ☰
          </button>
          <Link href="/" className="flex min-w-0 items-center gap-2">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-indigo-600 text-sm font-black text-white">
              D
            </span>
            <span className="truncate text-sm font-bold text-slate-900">
              Douyin Control Panel
            </span>
          </Link>
          <div className="ml-auto flex items-center gap-2">
            <LogoutButton />
          </div>
        </div>
      </header>

      <div className="mx-auto flex max-w-7xl gap-6 px-4 py-5 sm:px-6">
        {/* Desktop sidebar */}
        <aside className="hidden w-56 shrink-0 lg:block">
          <nav className="sticky top-20 flex flex-col gap-1">
            {nav.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-2 rounded-xl px-3 py-2 text-sm font-semibold ${
                  pathname === item.href
                    ? "bg-indigo-50 text-indigo-700"
                    : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                <span aria-hidden>{item.icon}</span>
                {item.label}
              </Link>
            ))}
            <p className="mt-4 px-3 text-[11px] leading-relaxed text-slate-400">
              Pipeline → Sources → Inventory → Destinations → Publications
            </p>
          </nav>
        </aside>

        {/* Mobile drawer */}
        {open ? (
          <div className="fixed inset-0 z-50 lg:hidden">
            <div
              className="absolute inset-0 bg-slate-900/50"
              onClick={() => setOpen(false)}
            />
            <div className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col bg-white p-4 shadow-xl">
              <div className="flex items-center justify-between">
                <span className="text-sm font-bold text-slate-900">Menu</span>
                <button
                  type="button"
                  aria-label="Đóng menu"
                  onClick={() => setOpen(false)}
                  className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-slate-200"
                >
                  ✕
                </button>
              </div>
              <nav className="mt-4 flex flex-col gap-1">
                {nav.map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={() => setOpen(false)}
                    className={`flex items-center gap-2 rounded-xl px-3 py-2.5 text-sm font-semibold ${
                      pathname === item.href
                        ? "bg-indigo-50 text-indigo-700"
                        : "text-slate-600 hover:bg-slate-100"
                    }`}
                  >
                    <span aria-hidden>{item.icon}</span>
                    {item.label}
                  </Link>
                ))}
              </nav>
            </div>
          </div>
        ) : null}

        <main className="min-w-0 flex-1">{children}</main>
      </div>
    </div>
  );
}
