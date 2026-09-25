import Link from "next/link";
import type { ReactNode } from "react";

export const CONTACT_EMAIL = "letanmedia.official@gmail.com";

/**
 * Shared chrome for public (unauthenticated) pages: landing, privacy, terms.
 * Uses the same design tokens as the dashboard (indigo brand, slate ink,
 * rounded-2xl surfaces) but renders no authenticated data and calls no
 * backend APIs.
 */
export function PublicHeader() {
  return (
    <header className="sticky top-0 z-40 border-b border-slate-200/80 bg-white/85 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-5xl items-center gap-3 px-4 sm:px-6">
        <Link href="/" className="flex min-w-0 items-center gap-2.5">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-indigo-700 text-base font-black text-white shadow-[0_4px_12px_-4px_rgba(79,70,229,0.6)]">
            L
          </span>
          <span className="min-w-0">
            <span className="block truncate text-sm font-extrabold tracking-tight text-slate-900">
              LETAN Media Sync
            </span>
            <span className="block text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">
              Publishing OS
            </span>
          </span>
        </Link>
        <nav className="ml-auto flex items-center gap-1 sm:gap-2">
          <Link
            href="/privacy"
            className="hidden rounded-lg px-3 py-2 text-sm font-semibold text-slate-600 transition hover:bg-slate-100 hover:text-slate-900 sm:inline-flex sm:min-h-[32px] sm:items-center"
          >
            Privacy
          </Link>
          <Link
            href="/terms"
            className="hidden rounded-lg px-3 py-2 text-sm font-semibold text-slate-600 transition hover:bg-slate-100 hover:text-slate-900 sm:inline-flex sm:min-h-[32px] sm:items-center"
          >
            Terms
          </Link>
          <Link
            href="/login"
            className="inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-[0_1px_2px_rgba(79,70,229,0.4)] transition hover:bg-indigo-500 sm:min-h-[38px]"
          >
            Sign in
          </Link>
        </nav>
      </div>
    </header>
  );
}

export function PublicFooter() {
  return (
    <footer className="border-t border-slate-200/70">
      <div className="mx-auto flex max-w-5xl flex-col gap-3 px-4 py-6 text-sm sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <p className="text-xs font-semibold text-slate-400">
          LETAN Media Sync · Video publishing &amp; YouTube channel management
        </p>
        <nav className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm font-semibold">
          <Link href="/privacy" className="text-indigo-600 transition hover:text-indigo-700 hover:underline">
            Privacy Policy
          </Link>
          <Link href="/terms" className="text-indigo-600 transition hover:text-indigo-700 hover:underline">
            Terms of Service
          </Link>
          <a
            href={`mailto:${CONTACT_EMAIL}`}
            className="text-indigo-600 transition hover:text-indigo-700 hover:underline"
          >
            Contact
          </a>
        </nav>
      </div>
    </footer>
  );
}

export function PublicShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col">
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 bg-[radial-gradient(800px_400px_at_50%_-80px,rgba(99,102,241,0.16),transparent_65%),radial-gradient(600px_320px_at_90%_110%,rgba(16,185,129,0.1),transparent_60%)]"
      />
      <PublicHeader />
      <main className="fade-up relative mx-auto w-full max-w-5xl flex-1 px-4 py-8 sm:px-6 sm:py-12">
        {children}
      </main>
      <PublicFooter />
    </div>
  );
}

/** Article card used by the legal pages. */
export function LegalCard({ children }: { children: ReactNode }) {
  return (
    <article className="rounded-2xl border border-slate-200/90 bg-white p-6 shadow-[0_1px_2px_rgba(15,23,42,0.05)] sm:p-8">
      {children}
    </article>
  );
}

export function LegalH2({ children }: { children: ReactNode }) {
  return (
    <h2 className="mt-8 text-base font-extrabold tracking-tight text-slate-900 first:mt-0">
      {children}
    </h2>
  );
}

export function LegalP({ children }: { children: ReactNode }) {
  return <p className="mt-3 text-sm leading-relaxed text-slate-600">{children}</p>;
}

export function LegalList({ items }: { items: ReactNode[] }) {
  return (
    <ul className="mt-3 list-disc space-y-2 pl-5 text-sm leading-relaxed text-slate-600 marker:text-indigo-400">
      {items.map((item, i) => (
        <li key={i}>{item}</li>
      ))}
    </ul>
  );
}

/** Monospace scope chip, e.g. youtube.readonly */
export function ScopeCode({ children }: { children: ReactNode }) {
  return (
    <code className="rounded-md bg-indigo-50 px-1.5 py-0.5 font-mono text-[12px] font-semibold text-indigo-700 ring-1 ring-inset ring-indigo-100">
      {children}
    </code>
  );
}
