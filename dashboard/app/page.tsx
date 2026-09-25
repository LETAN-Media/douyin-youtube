import Link from "next/link";
import { Shell } from "@/components/Shell";
import { Badge, Card, EmptyState, PageHeader, ProgressBar, StatCard } from "@/components/ui";
import { PublicShell } from "@/components/public";
import {
  IconAlert,
  IconChannels,
  IconChevronRight,
  IconClock,
  IconDestinations,
  IconEye,
  IconInventory,
  IconPlus,
  IconPublications,
  IconSources,
  IconUpload,
} from "@/components/icons";
import { getDashboard } from "@/lib/api";
import { formatTime } from "@/lib/format";
import { ApiError } from "@/lib/api";
import { isAuthenticated } from "@/lib/session";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  if (!(await isAuthenticated())) {
    return <PublicLanding />;
  }
  return <DashboardView />;
}

/**
 * Public landing page for guests (incl. Google OAuth reviewers).
 * No authenticated data, no backend calls, no ADMIN_TOKEN usage.
 */
function PublicLanding() {
  const features = [
    {
      icon: <IconUpload size={18} />,
      title: "Video publishing",
      text: "Upload videos to your connected YouTube channels on your schedule, with limits and metadata you control.",
    },
    {
      icon: <IconChannels size={18} />,
      title: "YouTube channel management",
      text: "Connect your own channels via Google OAuth and manage videos, publish status, and destinations in one workspace.",
    },
    {
      icon: <IconEye size={18} />,
      title: "Comment management",
      text: "Read comments on your videos and answer viewers with AI-assisted draft replies — reviewed by you or auto-posted within limits you set.",
    },
  ];
  const steps = [
    {
      n: "1",
      title: "Connect via Google OAuth",
      text: "Authorize only the YouTube channels you manage. You can revoke access at any time.",
    },
    {
      n: "2",
      title: "Configure publishing & replies",
      text: "Set schedules, daily limits, metadata preferences, and comment-reply rules per channel.",
    },
    {
      n: "3",
      title: "Publish & engage",
      text: "The app uploads per your configuration and helps you manage comments and replies.",
    },
  ];
  return (
    <PublicShell>
      <div className="overflow-hidden rounded-3xl border border-white/60 bg-white/90 shadow-[0_24px_60px_-24px_rgba(15,23,42,0.35)] backdrop-blur">
        <div className="bg-gradient-to-br from-indigo-600 via-indigo-600 to-violet-700 px-6 py-10 sm:px-10 sm:py-14">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-white/15 text-xl font-black text-white ring-1 ring-inset ring-white/25">
            L
          </div>
          <h1 className="mt-4 max-w-2xl text-2xl font-extrabold tracking-tight text-white sm:text-4xl">
            LETAN Media Sync
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-relaxed text-indigo-100 sm:text-base">
            Video publishing, YouTube channel management, and comment management
            for channels you operate — connect via Google OAuth, publish on
            your schedule, and answer viewers with AI-assisted replies you
            control.
          </p>
          <div className="mt-6 flex flex-wrap items-center gap-2">
            <Link
              href="/login"
              className="inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-xl bg-white px-5 py-2.5 text-sm font-bold text-indigo-700 shadow transition hover:bg-indigo-50"
            >
              Sign in / Open Dashboard
            </Link>
            <Link
              href="/privacy"
              className="inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-xl px-4 py-2.5 text-sm font-semibold text-white ring-1 ring-inset ring-white/40 transition hover:bg-white/10"
            >
              Privacy Policy
            </Link>
            <Link
              href="/terms"
              className="inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-xl px-4 py-2.5 text-sm font-semibold text-white ring-1 ring-inset ring-white/40 transition hover:bg-white/10"
            >
              Terms of Service
            </Link>
          </div>
        </div>

        <div className="px-6 py-8 sm:px-10">
          <h2 className="text-sm font-extrabold uppercase tracking-[0.1em] text-slate-500">
            What it does
          </h2>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            {features.map((f) => (
              <div
                key={f.title}
                className="rounded-2xl border border-slate-200/90 bg-white p-5"
              >
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600">
                  {f.icon}
                </span>
                <h3 className="mt-3 text-[15px] font-extrabold tracking-tight text-slate-900">
                  {f.title}
                </h3>
                <p className="mt-1.5 text-sm leading-relaxed text-slate-600">
                  {f.text}
                </p>
              </div>
            ))}
          </div>

          <h2 className="mt-8 text-sm font-extrabold uppercase tracking-[0.1em] text-slate-500">
            How it works
          </h2>
          <ol className="mt-3 grid gap-3 sm:grid-cols-3">
            {steps.map((s) => (
              <li
                key={s.n}
                className="rounded-2xl bg-slate-50 p-5 ring-1 ring-inset ring-slate-200/60"
              >
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 text-sm font-black text-white">
                  {s.n}
                </span>
                <h3 className="mt-3 text-sm font-extrabold text-slate-900">
                  {s.title}
                </h3>
                <p className="mt-1.5 text-sm leading-relaxed text-slate-600">
                  {s.text}
                </p>
              </li>
            ))}
          </ol>

          <Card className="mt-8 border-indigo-100 bg-indigo-50/50 p-5">
            <p className="text-sm font-bold text-slate-900">
              Operator sign-in required for the dashboard
            </p>
            <p className="mt-1 text-sm leading-relaxed text-slate-600">
              The control panel itself is restricted to the workspace operator.
              Reviewers can verify this app via the public pages below — no
              sign-in needed.
            </p>
            <div className="mt-3 flex flex-wrap gap-2 text-sm font-semibold">
              <Link href="/privacy" className="text-indigo-600 hover:underline">
                Privacy Policy
              </Link>
              <span aria-hidden className="text-slate-300">·</span>
              <Link href="/terms" className="text-indigo-600 hover:underline">
                Terms of Service
              </Link>
              <span aria-hidden className="text-slate-300">·</span>
              <a
                href="mailto:letanmedia.official@gmail.com"
                className="text-indigo-600 hover:underline"
              >
                Contact
              </a>
            </div>
          </Card>
        </div>
      </div>
    </PublicShell>
  );
}

async function DashboardView() {
  let rows: Awaited<ReturnType<typeof getDashboard>> | null = null;
  let loadError: string | null = null;
  try {
    rows = await getDashboard();
  } catch (e) {
    loadError = e instanceof ApiError ? e.message : "Không tải được dashboard.";
  }

  const totals = (rows ?? []).reduce(
    (acc, p) => ({
      pipelines: acc.pipelines + 1,
      sources: acc.sources + (p.sources_count ?? 0),
      inventory: acc.inventory + (p.inventory_total ?? 0),
      destinations: acc.destinations + (p.destinations_count ?? 0),
      publishedToday: acc.publishedToday + (p.published_today ?? 0),
      failed: acc.failed + (p.failed ?? 0),
      scheduled: acc.scheduled + (p.publications_scheduled ?? 0),
    }),
    {
      pipelines: 0,
      sources: 0,
      inventory: 0,
      destinations: 0,
      publishedToday: 0,
      failed: 0,
      scheduled: 0,
    },
  );

  return (
    <Shell>
      <PageHeader
        eyebrow="Workspace overview"
        title="Dashboard"
        description="Theo dõi toàn bộ pipelines Douyin → đa nền tảng tại một nơi."
        actions={
          <div className="flex items-center gap-2">
            <Link
              href="/channels"
              className="inline-flex min-h-[44px] items-center gap-1.5 rounded-xl border border-indigo-200 bg-indigo-50/70 px-4 py-2 text-sm font-bold text-indigo-700 shadow-sm transition hover:bg-indigo-100"
            >
              <IconChannels size={16} />
              Channel Workspaces
            </Link>
            <Link
              href="/pipelines/new"
              className="inline-flex min-h-[44px] items-center gap-1.5 rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-[0_4px_12px_-4px_rgba(79,70,229,0.6)] transition hover:bg-indigo-500"
            >
              <IconPlus size={16} />
              New Pipeline
            </Link>
          </div>
        }
      />

      {loadError ? (
        <Card className="mt-5 border-rose-200 p-5">
          <p className="flex items-center gap-2 text-sm font-bold text-rose-700">
            <IconAlert size={16} />
            Không tải được dữ liệu
          </p>
          <p className="mt-1 text-sm text-slate-600">{loadError}</p>
          <p className="mt-2 text-xs text-slate-500">
            Kiểm tra DOUYIN_API_URL / DOUYIN_ADMIN_TOKEN trên server.
          </p>
        </Card>
      ) : (
        <>
          <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
            <StatCard label="Pipelines" value={totals.pipelines} icon={<IconEye size={15} />} accent="indigo" />
            <StatCard label="Sources" value={totals.sources} icon={<IconSources size={15} />} accent="sky" />
            <StatCard label="Inventory" value={totals.inventory} icon={<IconInventory size={15} />} accent="slate" />
            <StatCard label="Destinations" value={totals.destinations} icon={<IconDestinations size={15} />} accent="emerald" />
            <StatCard label="Published today" value={totals.publishedToday} icon={<IconPublications size={15} />} accent="emerald" />
            <StatCard label="Scheduled" value={totals.scheduled} icon={<IconClock size={15} />} accent="amber" sub="Queued + scheduled" />
            <StatCard
              label="Failed"
              value={totals.failed}
              icon={<IconAlert size={15} />}
              accent="rose"
              alert={totals.failed > 0}
              sub={totals.failed > 0 ? "Cần xử lý retry" : "Mọi thứ ổn định"}
            />
          </div>

          {(rows ?? []).length === 0 ? (
            <Card className="mt-4">
              <EmptyState
                title="Chưa có pipeline nào"
                hint="Tạo pipeline đầu tiên để bắt đầu thu thập Douyin và phân phối đa nền tảng."
                action={
                  <Link
                    href="/pipelines/new"
                    className="inline-flex min-h-[44px] items-center gap-1.5 rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-500"
                  >
                    <IconPlus size={16} />
                    New Pipeline
                  </Link>
                }
              />
            </Card>
          ) : (
            <>
              <div className="mt-6 flex items-center justify-between">
                <h2 className="text-sm font-extrabold uppercase tracking-[0.1em] text-slate-500">
                  Pipelines · {rows?.length}
                </h2>
              </div>
              <div className="mt-3 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                {(rows ?? []).map((p) => {
                  const done = (p.inventory_total ?? 0) > 0
                    ? Math.round(((p.published_inventory ?? 0) / Math.max(1, p.inventory_total)) * 100)
                    : 0;
                  const noInventory = (p.inventory_available ?? p.inventory_total ?? 0) <= 0;
                  const reasonLabel = !p.enabled
                    ? null
                    : p.auto_reason === "NO_AVAILABLE_INVENTORY" || (noInventory && (p.published_today ?? 0) === 0)
                      ? "Auto ON · No videos available"
                      : p.auto_reason === "DESTINATION_NOT_CONNECTED"
                        ? "Auto ON · Destination not connected"
                        : p.auto_reason === "DAILY_LIMIT_REACHED"
                          ? "Auto ON · Daily limit reached"
                          : p.auto_reason === "WAITING_NEXT_SLOT"
                            ? "Auto ON · Waiting next slot"
                            : p.auto_reason === "SCHEDULER_DISABLED"
                              ? "Auto ON · Scheduler disabled"
                              : p.auto_reason === "WORKER_ERROR"
                                ? "Auto ON · Worker error"
                                : null;
                  return (
                    <Link
                      key={p.id}
                      href={`/pipelines/${p.id}`}
                      className="lift group rounded-2xl border border-slate-200/90 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.05)]"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex min-w-0 items-center gap-2.5">
                          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 text-sm font-black text-white">
                            {p.name.slice(0, 1).toUpperCase()}
                          </span>
                          <h3 className="min-w-0 truncate text-[15px] font-extrabold tracking-tight text-slate-900 group-hover:text-indigo-700">
                            {p.name}
                          </h3>
                        </div>
                        {p.enabled ? (
                          <Badge tone="green" dot>AUTO ON</Badge>
                        ) : (
                          <Badge tone="slate" dot>AUTO OFF</Badge>
                        )}
                      </div>

                      <dl className="mt-4 grid grid-cols-3 gap-2 text-center">
                        {[
                          { l: "Sources", v: p.sources_count },
                          { l: "Inventory", v: p.inventory_total },
                          { l: "Dest.", v: p.destinations_count },
                        ].map((s) => (
                          <div key={s.l} className="rounded-xl bg-slate-50 px-2 py-2.5">
                            <dt className="text-[10px] font-bold uppercase tracking-wider text-slate-400">{s.l}</dt>
                            <dd className="tnum mt-0.5 text-lg font-extrabold text-slate-900">{s.v}</dd>
                          </div>
                        ))}
                      </dl>

                      <div className="mt-3">
                        <div className="flex items-center justify-between text-[11px] font-semibold text-slate-500">
                          <span>Published {p.published_inventory}/{p.inventory_total}</span>
                          <span className="tnum">{done}%</span>
                        </div>
                        <div className="mt-1.5">
                          <ProgressBar value={done} tone={p.failed > 0 ? "amber" : "indigo"} />
                        </div>
                        {reasonLabel ? (
                          <p className="mt-2 rounded-lg bg-amber-50 px-2.5 py-1.5 text-[11px] font-bold text-amber-700">
                            {reasonLabel}
                          </p>
                        ) : null}
                      </div>

                      <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3 text-xs">
                        <span className="flex items-center gap-1.5 text-slate-500">
                          <IconClock size={13} />
                          {formatTime(p.next_upload)}
                        </span>
                        {p.failed > 0 ? (
                          <span className="flex items-center gap-1 font-bold text-rose-600">
                            <IconAlert size={13} />
                            {p.failed} failed
                          </span>
                        ) : (
                          <span className="flex items-center gap-1 font-bold text-emerald-600">
                            Hôm nay +{p.published_today}
                          </span>
                        )}
                        <span className="flex items-center gap-0.5 font-bold text-indigo-600 opacity-0 transition group-hover:opacity-100">
                          Mở
                          <IconChevronRight size={14} />
                        </span>
                      </div>
                    </Link>
                  );
                })}
              </div>
            </>
          )}
        </>
      )}
    </Shell>
  );
}
