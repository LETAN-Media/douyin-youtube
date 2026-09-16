import Link from "next/link";
import { Shell } from "@/components/Shell";
import { Badge, Card, EmptyState, PageHeader, ProgressBar, StatCard } from "@/components/ui";
import {
  IconAlert,
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

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
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
              href="/manual"
              className="inline-flex min-h-[44px] items-center gap-1.5 rounded-xl border border-indigo-200 bg-indigo-50/70 px-4 py-2 text-sm font-bold text-indigo-700 shadow-sm transition hover:bg-indigo-100"
            >
              <IconUpload size={16} />
              Manual Publish
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

      <div className="mt-4 flex items-center gap-2">
        <div className="inline-flex rounded-xl bg-slate-100 p-1">
          <span className="inline-flex items-center gap-1.5 rounded-lg bg-white px-3.5 py-1.5 text-xs font-extrabold text-indigo-700 shadow-sm">
            <span className="h-2 w-2 rounded-full bg-indigo-600" />
            Auto Mode
          </span>
          <Link
            href="/manual"
            className="inline-flex items-center gap-1.5 rounded-lg px-3.5 py-1.5 text-xs font-semibold text-slate-600 transition hover:text-slate-900"
          >
            <IconUpload size={14} />
            Manual Publish
          </Link>
        </div>
      </div>

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
