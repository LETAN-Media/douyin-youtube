"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { IconDashboard, IconLogout, IconMenu, IconPlus, IconX } from "./icons";

const nav = [
  { href: "/", label: "Dashboard", icon: <IconDashboard size={17} /> },
  { href: "/pipelines/new", label: "New Pipeline", icon: <IconPlus size={17} /> },
];

function LogoutButton({ compact = false }: { compact?: boolean }) {
  const router = useRouter();
  return (
    <button
      type="button"
      className={
        compact
          ? "inline-flex min-h-[44px] items-center gap-1.5 rounded-xl px-3 py-2 text-xs font-semibold text-slate-500 transition hover:bg-slate-100 hover:text-slate-700"
          : "inline-flex min-h-[40px] items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-600 shadow-sm transition hover:border-slate-300 hover:bg-slate-50"
      }
      onClick={async () => {
        try {
          await fetch("/api/auth/logout", { method: "POST" });
        } finally {
          router.push("/login");
          router.refresh();
        }
      }}
    >
      <IconLogout size={15} />
      Đăng xuất
    </button>
  );
}

function Brand() {
  return (
    <Link href="/" className="flex min-w-0 items-center gap-2.5">
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-indigo-700 text-base font-black text-white shadow-[0_4px_12px_-4px_rgba(79,70,229,0.6)]">
        D
      </span>
      <span className="min-w-0">
        <span className="block truncate text-sm font-extrabold tracking-tight text-slate-900">
          Douyin Panel
        </span>
        <span className="block text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">
          Publishing OS
        </span>
      </span>
    </Link>
  );
}

function NavItems({ onNavigate, pathname }: { onNavigate?: () => void; pathname: string }) {
  return (
    <nav className="flex flex-col gap-1">
      {nav.map((item) => {
        const active =
          item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={`flex min-h-[44px] items-center gap-2.5 rounded-xl px-3 py-2 text-sm font-semibold transition ${
              active
                ? "bg-indigo-600 text-white shadow-[0_4px_12px_-4px_rgba(79,70,229,0.6)]"
                : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
            }`}
          >
            <span aria-hidden className={active ? "text-white" : "text-slate-400"}>
              {item.icon}
            </span>
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  return (
    <div className="min-h-dvh lg:flex">
      {/* Desktop sidebar */}
      <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r border-slate-200/80 bg-white/80 px-4 py-5 backdrop-blur lg:flex">
        <Brand />
        <div className="mt-6">
          <p className="px-3 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400">
            Workspace
          </p>
          <div className="mt-2">
            <NavItems pathname={pathname} />
          </div>
        </div>
        <div className="mt-6 rounded-2xl border border-slate-200/80 bg-slate-50/80 p-3.5">
          <p className="text-[11px] font-bold uppercase tracking-[0.1em] text-slate-400">
            Pipeline flow
          </p>
          <p className="mt-1.5 text-xs leading-relaxed text-slate-500">
            Sources → Inventory → Destinations → Publications
          </p>
        </div>
        <div className="mt-auto flex items-center justify-between gap-2 border-t border-slate-100 pt-4">
          <span className="inline-flex items-center gap-1.5 px-1 text-xs font-semibold text-slate-500">
            <span className="h-2 w-2 rounded-full bg-emerald-500" />
            Operational
          </span>
          <LogoutButton compact />
        </div>
      </aside>

      {/* Mobile topbar */}
      <header className="sticky top-0 z-40 border-b border-slate-200/80 bg-white/85 backdrop-blur lg:hidden">
        <div className="flex h-14 items-center gap-2.5 px-4">
          <button
            type="button"
            aria-label="Mở menu"
            onClick={() => setOpen(true)}
            className="inline-flex h-11 w-11 items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-700 shadow-sm"
          >
            <IconMenu size={19} />
          </button>
          <Brand />
          <div className="ml-auto">
            <LogoutButton />
          </div>
        </div>
      </header>

      {/* Desktop topbar spacer is the sidebar; content */}
      <div className="min-w-0 flex-1">
        <div className="mx-auto max-w-7xl px-4 py-5 sm:px-6 lg:py-7">
          <main className="fade-up min-w-0">{children}</main>
          <footer className="mt-10 flex items-center justify-between border-t border-slate-200/70 pt-4 text-[11px] text-slate-400">
            <span>Douyin Control Panel · Multi-destination publishing</span>
            <span className="hidden sm:inline">Pipeline → Sources → Inventory → Destinations → Publications</span>
          </footer>
        </div>
      </div>

      {/* Mobile drawer */}
      {open ? (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div
            className="absolute inset-0 bg-slate-900/50 backdrop-blur-[2px]"
            onClick={() => setOpen(false)}
          />
          <div className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col bg-white p-4 shadow-2xl">
            <div className="flex items-center justify-between">
              <Brand />
              <button
                type="button"
                aria-label="Đóng menu"
                onClick={() => setOpen(false)}
                className="inline-flex h-11 w-11 items-center justify-center rounded-xl border border-slate-200 text-slate-600"
              >
                <IconX size={18} />
              </button>
            </div>
            <div className="mt-5">
              <NavItems pathname={pathname} onNavigate={() => setOpen(false)} />
            </div>
            <div className="mt-auto border-t border-slate-100 pt-4">
              <LogoutButton compact />
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
