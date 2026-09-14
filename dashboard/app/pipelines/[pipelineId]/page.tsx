import Link from "next/link";
import { notFound } from "next/navigation";
import { Shell } from "@/components/Shell";
import { Badge, Card } from "@/components/ui";
import { IconBack } from "@/components/icons";
import {
  getDestinationStatuses,
  getFlowState,
  getPipeline,
  listDestinations,
  listInventory,
  listPublications,
  listSources,
} from "@/lib/api";
import { ApiError } from "@/lib/api";
import { PipelineToggle } from "@/components/pipeline/PipelineToggle";

export const dynamic = "force-dynamic";
import { SourcesPanel } from "@/components/pipeline/SourcesPanel";
import { InventoryPanel } from "@/components/pipeline/InventoryPanel";
import { DestinationsPanel } from "@/components/pipeline/DestinationsPanel";
import { PublicationsPanel } from "@/components/pipeline/PublicationsPanel";
import { PipelineFlowGraph } from "@/components/pipeline/PipelineFlowGraph";
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
  // overview: flow-state only (1: nodes + summary + initial routes).
  // sources: sources only (1).
  // inventory: inventory + sources(filter) + destinations(publish) (3).
  // destinations: destinations + batch statuses (2, was 1+N).
  // publications: publications + destinations(names) (2).
  // ai-profile/settings: pipeline only (0 extra).
  type Fetched = {
    flow?: Awaited<ReturnType<typeof getFlowState>> | null;
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
    apiCalls.push("getFlowState");
    data.flow = await getFlowState(pipelineId).catch(() => null);
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

  return (
    <Shell>
      <Link
        href="/"
        className="inline-flex min-h-[44px] items-center gap-1.5 rounded-lg px-2 py-1 text-sm font-semibold text-slate-500 transition hover:bg-slate-200/60 hover:text-slate-800 sm:min-h-[32px]"
      >
        <IconBack size={15} />
        Dashboard
      </Link>

      <Card className="mt-1 overflow-hidden p-0">
        <div className="h-1.5 bg-gradient-to-r from-indigo-500 via-violet-500 to-emerald-400" />
        <div className="flex flex-wrap items-center justify-between gap-3 p-4 sm:px-5">
          <div className="flex min-w-0 items-center gap-3">
            <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-600 text-lg font-black text-white shadow-[0_6px_16px_-6px_rgba(79,70,229,0.7)]">
              {pipeline.name.slice(0, 1).toUpperCase()}
            </span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="truncate text-xl font-extrabold tracking-tight text-slate-900">
                  {pipeline.name}
                </h1>
                {pipeline.enabled ? (
                  <Badge tone="green" dot>AUTO ON</Badge>
                ) : (
                  <Badge tone="slate" dot>AUTO OFF</Badge>
                )}
              </div>
              <p className="mt-0.5 truncate text-[13px] text-slate-500">
                <span className="font-mono">/{pipeline.slug}</span>
                <span className="mx-1.5 text-slate-300">·</span>
                {pipeline.timezone}
                <span className="mx-1.5 text-slate-300">·</span>
                {pipeline.default_privacy}
              </p>
            </div>
          </div>
          <PipelineToggle id={pipeline.id} enabled={pipeline.enabled} />
        </div>
      </Card>

      {/* Instant tabs: optimistic active state + spinner, >=44px touch target */}
      <PipelineTabs pipelineId={pipelineId} activeTab={activeTab} />

      <div className="mt-4">
        {activeTab === "overview" ? (
          data.flow ? (
            <PipelineFlowGraph key={pipelineId} pipelineId={pipelineId} initial={data.flow} />
          ) : (
            <Card className="p-5">
              <p className="text-sm font-bold text-rose-700">Không tải được flow state</p>
              <p className="mt-1 text-sm text-slate-600">
                Backend không trả dữ liệu graph. Kiểm tra kết nối rồi tải lại trang.
              </p>
            </Card>
          )
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
