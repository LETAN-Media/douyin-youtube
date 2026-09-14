import Link from "next/link";
import { notFound } from "next/navigation";
import { Shell } from "@/components/Shell";
import { Badge, Card } from "@/components/ui";
import {
  getDestinationStatuses,
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
import { PipelineTabs, type PipelineTabKey } from "@/components/pipeline/PipelineTabs";

const TAB_KEYS: PipelineTabKey[] = [
  "overview",
  "sources",
  "inventory",
  "destinations",
  "publications",
  "ai-profile",
  "settings",
];

export default async function PipelineDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ pipelineId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  // eslint-disable-next-line react-hooks/purity -- server timing log, not render state
  const renderT0 = Date.now();
  const { pipelineId } = await params;
  const sp = await searchParams;
  const tabRaw = typeof sp.tab === "string" ? sp.tab : "overview";
  const activeTab: PipelineTabKey = (TAB_KEYS as string[]).includes(tabRaw)
    ? (tabRaw as PipelineTabKey)
    : "overview";

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

  // ---- Tab-specific fetching: 1-3 backend calls max per navigation ----
  // overview: stats only (1). sources: sources only (1).
  // inventory: inventory + sources(filter) + destinations(publish) (3).
  // destinations: destinations + batch statuses (2, was 1+N).
  // publications: publications + destinations(names) (2).
  // ai-profile/settings: pipeline only (0 extra).
  type Fetched = {
    stats?: Awaited<ReturnType<typeof getPipelineStats>> | null;
    sources?: Awaited<ReturnType<typeof listSources>>;
    destinations?: Awaited<ReturnType<typeof listDestinations>>;
    statusById?: Record<string, import("@/lib/types").DestinationStatus | null>;
    publications?: Awaited<ReturnType<typeof listPublications>>;
    inventory?: Awaited<ReturnType<typeof listInventory>> | null;
    invPage?: number;
    invStatus?: string;
    invSearch?: string;
    invSource?: string;
    pubStatusFilter?: string;
  };
  const data: Fetched = {};
  const apiCalls: string[] = ["getPipeline"];
  // eslint-disable-next-line react-hooks/purity -- server timing log
  const tFetch0 = Date.now();

  if (activeTab === "overview") {
    apiCalls.push("getPipelineStats");
    data.stats = await getPipelineStats(pipelineId).catch(() => null);
  } else if (activeTab === "sources") {
    apiCalls.push("listSources");
    data.sources = await listSources(pipelineId).catch(() => []);
  } else if (activeTab === "inventory") {
    const invPage = Math.max(1, Number(getParam("page") ?? 1) || 1);
    const invStatus = getParam("status") ?? "all";
    const invSearch = getParam("q") ?? "";
    const invSource = getParam("source_id") ?? "";
    data.invPage = invPage;
    data.invStatus = invStatus;
    data.invSearch = invSearch;
    data.invSource = invSource;
    apiCalls.push("listInventory", "listSources(filter)", "listDestinations(min)");
    const [inventory, sources, destinations] = await Promise.all([
      listInventory(pipelineId, {
        status: invStatus === "all" ? undefined : invStatus,
        search: invSearch || undefined,
        source_id: invSource || undefined,
        page: invPage,
        page_size: 20,
      }).catch(() => null),
      listSources(pipelineId).catch(() => []),
      listDestinations(pipelineId).catch(() => []),
    ]);
    data.inventory = inventory;
    data.sources = sources;
    data.destinations = destinations;
  } else if (activeTab === "destinations") {
    apiCalls.push("listDestinations", "getDestinationStatuses(batch)");
    const destinations = await listDestinations(pipelineId).catch(() => []);
    data.destinations = destinations;
    // Single batch request replaces N per-destination status calls.
    const batch = await getDestinationStatuses(pipelineId).catch(() => []);
    const byId: Record<string, import("@/lib/types").DestinationStatus | null> = {};
    for (const b of batch) {
      byId[b.destination_id] = {
        connected: b.connected,
        platform: b.platform,
        name: b.name,
        daily_upload_limit: b.daily_upload_limit,
        today_published: b.today_published,
        next_upload: b.next_upload ?? null,
        enabled: b.enabled,
      };
    }
    // Ensure every destination has a key (null = unknown, card falls back).
    for (const d of destinations) {
      if (!(d.id in byId)) byId[d.id] = null;
    }
    data.statusById = byId;
  } else if (activeTab === "publications") {
    const pubStatusFilter = getParam("pub_status") ?? "all";
    data.pubStatusFilter = pubStatusFilter;
    apiCalls.push("listPublications", "listDestinations(min)");
    // Server-side status filter: 1 query instead of client filter over 200 rows.
    const [publications, destinations] = await Promise.all([
      listPublications({
        pipeline_id: pipelineId,
        limit: 200,
        ...(pubStatusFilter !== "all" ? { status: pubStatusFilter } : {}),
      }).catch(() => []),
      listDestinations(pipelineId).catch(() => []),
    ]);
    data.publications = publications;
    data.destinations = destinations;
  }
  // ai-profile / settings: pipeline only, no extra calls.

  if (process.env.NODE_ENV !== "production") {
    // eslint-disable-next-line react-hooks/purity -- server timing log only
    const fetchMs = Date.now() - tFetch0;
    // eslint-disable-next-line react-hooks/purity -- server timing log only
    const totalMs = Date.now() - renderT0;
    console.log(
      `[pipeline] tab=${activeTab} calls=${apiCalls.join(",")} fetch=${fetchMs}ms total=${totalMs}ms`,
    );
  }

  const tabHref = (key: string, extra: Record<string, string> = {}) => {
    const q = new URLSearchParams({ tab: key, ...extra });
    return `/pipelines/${pipelineId}?${q.toString()}`;
  };

  return (
    <Shell>
      <Link href="/" className="inline-flex min-h-[44px] items-center text-sm font-semibold text-indigo-600">
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

      {/* Instant tabs: optimistic active state + spinner, >=44px touch target */}
      <PipelineTabs pipelineId={pipelineId} activeTab={activeTab} />

      <div className="mt-4">
        {activeTab === "overview" ? (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {[
              { label: "Sources", value: data.stats?.sources_count ?? "—" },
              { label: "Inventory", value: data.stats?.inventory_total ?? "—" },
              { label: "Backlog", value: data.stats?.backlog ?? "—" },
              { label: "New", value: data.stats?.new ?? "—" },
              { label: "Destinations", value: data.stats?.destinations_count ?? "—" },
              { label: "Published today", value: data.stats?.published_today ?? "—" },
              { label: "Failed", value: data.stats?.failed ?? "—" },
              { label: "Scheduled", value: data.stats?.publications_scheduled ?? "—" },
            ].map((s) => (
              <div key={s.label} className="rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{s.label}</p>
                <p className="mt-1 text-2xl font-bold text-slate-900">{s.value}</p>
              </div>
            ))}
            <Card className="p-4 sm:col-span-2 xl:col-span-4">
              <p className="text-sm font-semibold text-slate-900">Next publication</p>
              <p className="mt-1 text-sm text-slate-600">
                {data.stats?.next_publication ? formatTime(data.stats.next_publication) : "—"}
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Link href={tabHref("sources")} className="inline-flex min-h-[44px] items-center rounded-xl border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50">
                  Manage sources →
                </Link>
                <Link href={tabHref("destinations")} className="inline-flex min-h-[44px] items-center rounded-xl border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50">
                  Manage destinations →
                </Link>
                <Link href={tabHref("inventory")} className="inline-flex min-h-[44px] items-center rounded-xl border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50">
                  View inventory →
                </Link>
              </div>
            </Card>
          </div>
        ) : null}

        {activeTab === "sources" ? (
          <SourcesPanel pipelineId={pipelineId} sources={data.sources ?? []} />
        ) : null}

        {activeTab === "inventory" ? (
          <InventoryPanel
            pipelineId={pipelineId}
            inventory={data.inventory ?? null}
            sources={data.sources ?? []}
            destinations={data.destinations ?? []}
            current={{ page: data.invPage ?? 1, status: data.invStatus ?? "all", q: data.invSearch ?? "", source_id: data.invSource ?? "" }}
          />
        ) : null}

        {activeTab === "destinations" ? (
          <DestinationsPanel
            pipelineId={pipelineId}
            destinations={data.destinations ?? []}
            statusById={data.statusById ?? {}}
            oauthSuccess={getParam("oauth") === "success"}
          />
        ) : null}

        {activeTab === "publications" ? (
          <PublicationsPanel
            pipelineId={pipelineId}
            publications={data.publications ?? []}
            destinations={data.destinations ?? []}
            currentFilter={data.pubStatusFilter ?? "all"}
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
