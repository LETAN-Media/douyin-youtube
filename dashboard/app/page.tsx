import Link from "next/link";
import { Shell } from "@/components/Shell";
import { Badge, Card, EmptyState } from "@/components/ui";
import { getDashboard } from "@/lib/api";
import { formatTime } from "@/lib/format";
import { ApiError } from "@/lib/api";

export const dynamic = "force-dynamic";

function Stat({
  label,
  value,
}: {
  label: string;
  value: string | number;
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
        {label}
      </p>
      <p className="mt-1 text-2xl font-bold text-slate-900">{value}</p>
    </div>
  );
}

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
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Dashboard</h1>
          <p className="mt-0.5 text-sm text-slate-500">
            Pipeline → Sources → Inventory → Destinations → Publications
          </p>
        </div>
        <Link
          href="/pipelines/new"
          className="inline-flex items-center rounded-xl bg-indigo-600 px-3.5 py-2 text-sm font-semibold text-white hover:bg-indigo-500"
        >
          + New Pipeline
        </Link>
      </div>

      {loadError ? (
        <Card className="mt-4 p-5">
          <p className="text-sm font-semibold text-red-700">
            Không tải được dữ liệu
          </p>
          <p className="mt-1 text-sm text-slate-600">{loadError}</p>
          <p className="mt-2 text-xs text-slate-500">
            Kiểm tra DOUYIN_API_URL / DOUYIN_ADMIN_TOKEN trên server.
          </p>
        </Card>
      ) : (
        <>
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-7">
            <Stat label="Pipelines" value={totals.pipelines} />
            <Stat label="Sources" value={totals.sources} />
            <Stat label="Inventory" value={totals.inventory} />
            <Stat label="Destinations" value={totals.destinations} />
            <Stat label="Published today" value={totals.publishedToday} />
            <Stat label="Failed" value={totals.failed} />
            <Stat label="Scheduled" value={totals.scheduled} />
          </div>

          {(rows ?? []).length === 0 ? (
            <Card className="mt-4">
              <EmptyState
                title="Chưa có pipeline nào"
                hint="Tạo pipeline đầu tiên để bắt đầu thu thập Douyin và phân phối đa nền tảng."
                action={
                  <Link
                    href="/pipelines/new"
                    className="inline-flex items-center rounded-xl bg-indigo-600 px-3.5 py-2 text-sm font-semibold text-white hover:bg-indigo-500"
                  >
                    + New Pipeline
                  </Link>
                }
              />
            </Card>
          ) : (
            <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {(rows ?? []).map((p) => (
                <Link
                  key={p.id}
                  href={`/pipelines/${p.id}`}
                  className="group rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-indigo-200 hover:shadow"
                >
                  <div className="flex items-start justify-between gap-2">
                    <h2 className="min-w-0 truncate text-base font-bold text-slate-900 group-hover:text-indigo-700">
                      {p.name}
                    </h2>
                    {p.enabled ? (
                      <Badge tone="green">AUTO ON</Badge>
                    ) : (
                      <Badge tone="slate">AUTO OFF</Badge>
                    )}
                  </div>
                  <dl className="mt-4 space-y-2 text-sm">
                    <div className="flex justify-between gap-2">
                      <dt className="text-slate-500">Sources</dt>
                      <dd className="font-semibold">{p.sources_count}</dd>
                    </div>
                    <div className="flex justify-between gap-2">
                      <dt className="text-slate-500">Inventory</dt>
                      <dd className="font-semibold">{p.inventory_total}</dd>
                    </div>
                    <div className="flex justify-between gap-2">
                      <dt className="text-slate-500">Destinations</dt>
                      <dd className="font-semibold">{p.destinations_count}</dd>
                    </div>
                    <div className="flex justify-between gap-2">
                      <dt className="text-slate-500">Published today</dt>
                      <dd className="font-semibold">{p.published_today}</dd>
                    </div>
                    <div className="flex justify-between gap-2">
                      <dt className="text-slate-500">Failed</dt>
                      <dd
                        className={`font-semibold ${p.failed > 0 ? "text-red-600" : ""}`}
                      >
                        {p.failed}
                      </dd>
                    </div>
                    <div className="flex justify-between gap-2">
                      <dt className="text-slate-500">Next publication</dt>
                      <dd className="text-right font-semibold">
                        {formatTime(p.next_upload)}
                      </dd>
                    </div>
                  </dl>
                </Link>
              ))}
            </div>
          )}
        </>
      )}
    </Shell>
  );
}
