import Link from "next/link";
import { notFound } from "next/navigation";
import { Shell } from "@/components/Shell";
import { Badge, Card } from "@/components/ui";
import {
  getDestinationStatus,
  getPipeline,
  getPipelineStats,
  listDestinations,
  listInventory,
  listPublications,
  listSources,
} from "@/lib/api";
import { ApiError } from "@/lib/api";
import { formatTime } from "@/lib/format";
import { PipelineToggle } from "@/components/pipeline/PipelineToggle";

export const dynamic = "force-dynamic";
import { SourcesPanel } from "@/components/pipeline/SourcesPanel";
import { InventoryPanel } from "@/components/pipeline/InventoryPanel";
import { DestinationsPanel } from "@/components/pipeline/DestinationsPanel";
import { PublicationsPanel } from "@/components/pipeline/PublicationsPanel";
import { AiProfileForm, SettingsForm, DangerZone } from "@/components/pipeline/PipelineForms";

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "sources", label: "Sources" },
  { key: "inventory", label: "Inventory" },
  { key: "destinations", label: "Destinations" },
  { key: "publications", label: "Publications" },
  { key: "ai-profile", label: "AI Profile" },
  { key: "settings", label: "Settings" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export default async function PipelineDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ pipelineId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { pipelineId } = await params;
  const sp = await searchParams;
  const tab = (typeof sp.tab === "string" ? sp.tab : "overview") as TabKey;
  const activeTab: TabKey = TABS.some((t) => t.key === tab) ? tab : "overview";

  const getParam = (k: string) =>
    typeof sp[k] === "string" ? (sp[k] as string) : undefined;

  let pipeline;
  try {
    pipeline = await getPipeline(pipelineId);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    return (
      <Shell>
        <Card className="p-5">
          <p className="text-sm font-semibold text-red-700">Không tải được pipeline</p>
          <p className="mt-1 text-sm text-slate-600">
            {e instanceof Error ? e.message : "Lỗi không xác định."}
          </p>
          <Link href="/" className="mt-3 inline-block text-sm font-semibold text-indigo-600">
            ← Dashboard
          </Link>
        </Card>
      </Shell>
    );
  }

  const [stats, sources, destinations, publications] = await Promise.all([
    getPipelineStats(pipelineId).catch(() => null),
    listSources(pipelineId).catch(() => []),
    listDestinations(pipelineId).catch(() => []),
    listPublications({ pipeline_id: pipelineId, limit: 200 }).catch(() => []),
  ]);

  const destStatuses = await Promise.all(
    destinations.map((d) =>
      getDestinationStatus(d.id)
        .then((s) => ({ id: d.id, status: s }))
        .catch(() => ({ id: d.id, status: null })),
    ),
  );
  const statusById = new Map(destStatuses.map((s) => [s.id, s.status]));

  // Inventory params (server-side pagination + filter via URL)
  const invPage = Math.max(1, Number(getParam("page") ?? 1) || 1);
  const invStatus = getParam("status") ?? "all";
  const invSearch = getParam("q") ?? "";
  const invSource = getParam("source_id") ?? "";
  const inventory = await listInventory(pipelineId, {
    status: invStatus === "all" ? undefined : invStatus,
    search: invSearch || undefined,
    source_id: invSource || undefined,
    page: invPage,
    page_size: 20,
  }).catch(() => null);

  const pubStatusFilter = getParam("pub_status") ?? "all";
  const filteredPubs =
    pubStatusFilter === "all"
      ? publications
      : publications.filter((p) => p.status === pubStatusFilter);

  const tabHref = (key: string, extra: Record<string, string> = {}) => {
    const q = new URLSearchParams({ tab: key, ...extra });
    return `/pipelines/${pipelineId}?${q.toString()}`;
  };

  return (
    <Shell>
      <Link href="/" className="text-sm font-semibold text-indigo-600">
        ← Dashboard
      </Link>
      <div className="mt-2 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="truncate text-xl font-bold text-slate-900">
              {pipeline.name}
            </h1>
            {pipeline.enabled ? (
              <Badge tone="green">AUTO ON</Badge>
            ) : (
              <Badge tone="slate">AUTO OFF</Badge>
            )}
          </div>
          <p className="mt-0.5 text-sm text-slate-500">
            /{pipeline.slug} · {pipeline.timezone} · {pipeline.default_privacy}
          </p>
        </div>
        <PipelineToggle id={pipeline.id} enabled={pipeline.enabled} />
      </div>

      {/* Tabs: scrollable on mobile */}
      <div className="sticky top-14 z-30 -mx-4 mt-4 border-y border-slate-200 bg-[#f1f5f9]/95 px-4 backdrop-blur sm:-mx-6 sm:px-6">
        <nav className="mx-auto flex max-w-7xl gap-1 overflow-x-auto py-2">
          {TABS.map((t) => (
            <Link
              key={t.key}
              href={tabHref(t.key)}
              className={`shrink-0 rounded-xl px-3 py-2 text-sm font-semibold ${
                activeTab === t.key
                  ? "bg-indigo-600 text-white"
                  : "text-slate-600 hover:bg-slate-200/70"
              }`}
            >
              {t.label}
            </Link>
          ))}
        </nav>
      </div>

      <div className="mt-4">
        {activeTab === "overview" ? (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {[
              { label: "Sources", value: stats?.sources_count ?? sources.length },
              { label: "Inventory", value: stats?.inventory_total ?? "—" },
              { label: "Backlog", value: stats?.backlog ?? "—" },
              { label: "New", value: stats?.new ?? "—" },
              { label: "Destinations", value: stats?.destinations_count ?? destinations.length },
              { label: "Published today", value: stats?.published_today ?? "—" },
              { label: "Failed", value: stats?.failed ?? "—" },
              { label: "Scheduled", value: stats?.publications_scheduled ?? "—" },
            ].map((s) => (
              <div key={s.label} className="rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{s.label}</p>
                <p className="mt-1 text-2xl font-bold text-slate-900">{s.value}</p>
              </div>
            ))}
            <Card className="p-4 sm:col-span-2 xl:col-span-4">
              <p className="text-sm font-semibold text-slate-900">Next publication</p>
              <p className="mt-1 text-sm text-slate-600">
                {stats?.next_publication ? formatTime(stats.next_publication) : "—"}
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Link href={tabHref("sources")} className="rounded-xl border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50">
                  Manage sources →
                </Link>
                <Link href={tabHref("destinations")} className="rounded-xl border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50">
                  Manage destinations →
                </Link>
                <Link href={tabHref("inventory")} className="rounded-xl border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50">
                  View inventory →
                </Link>
              </div>
            </Card>
          </div>
        ) : null}

        {activeTab === "sources" ? (
          <SourcesPanel pipelineId={pipelineId} sources={sources} />
        ) : null}

        {activeTab === "inventory" ? (
          <InventoryPanel
            pipelineId={pipelineId}
            inventory={inventory}
            sources={sources}
            destinations={destinations}
            current={{ page: invPage, status: invStatus, q: invSearch, source_id: invSource }}
          />
        ) : null}

        {activeTab === "destinations" ? (
          <DestinationsPanel
            pipelineId={pipelineId}
            destinations={destinations}
            statusById={Object.fromEntries(
              [...statusById.entries()].map(([k, v]) => [k, v]),
            )}
            oauthSuccess={getParam("oauth") === "success"}
          />
        ) : null}

        {activeTab === "publications" ? (
          <PublicationsPanel
            pipelineId={pipelineId}
            publications={filteredPubs}
            destinations={destinations}
            currentFilter={pubStatusFilter}
          />
        ) : null}

        {activeTab === "ai-profile" ? (
          <AiProfileForm pipelineId={pipelineId} pipeline={pipeline} />
        ) : null}

        {activeTab === "settings" ? (
          <div className="space-y-4">
            <SettingsForm pipelineId={pipelineId} pipeline={pipeline} />
            <DangerZone pipelineId={pipelineId} name={pipeline.name} />
          </div>
        ) : null}
      </div>
    </Shell>
  );
}
