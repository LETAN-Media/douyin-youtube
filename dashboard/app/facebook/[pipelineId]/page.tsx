import Link from "next/link";
import { notFound } from "next/navigation";
import { Shell } from "@/components/Shell";
import { Badge } from "@/components/ui";
import { IconBack } from "@/components/icons";
import {
  FacebookApiError,
  getFacebookAiSample,
  getFacebookAiSettings,
  getFacebookAiStats,
  getFacebookPipelineDetail,
  getFacebookReelAiMetadata,
  getFacebookScheduleStatus,
  getFacebookSchedule,
  listFacebookDestinations,
  listFacebookInventory,
  listFacebookPublications,
  listFacebookSources,
} from "@/lib/facebook-api";
import type { FacebookAiSettingsDto, FacebookFlowState, FacebookScheduleDto } from "@/lib/facebook-api";
import { getFacebookFlowState } from "@/lib/facebook-api";
import { FacebookTabs, type FacebookTabKey } from "@/components/facebook/FacebookTabs";
import { FacebookOverview } from "@/components/facebook/FacebookOverview";
import { FacebookSources } from "@/components/facebook/FacebookSources";
import { FacebookInventory } from "@/components/facebook/FacebookInventory";
import { FacebookDestinations } from "@/components/facebook/FacebookDestinations";
import { FacebookPublications } from "@/components/facebook/FacebookPublications";
import { FacebookAiProcessing } from "@/components/facebook/FacebookAiProcessing";
import { FacebookScheduler } from "@/components/facebook/FacebookScheduler";

const TABS: FacebookTabKey[] = [
  "overview",
  "sources",
  "inventory",
  "destinations",
  "publications",
  "ai-processing",
  "scheduler",
];

function MissingPipeline() {
  return (
    <Shell>
      <div className="w-full min-w-0">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <h1 className="truncate text-xl font-extrabold tracking-tight text-slate-900 sm:text-2xl">Facebook</h1>
            <p className="mt-1 text-sm text-slate-500">Chi tiết pipeline</p>
          </div>
          <Link href="/facebook" className="inline-flex min-h-[44px] items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 shrink-0">
            <IconBack size={15} />
            Facebook
          </Link>
        </div>
        <div className="mt-6 rounded-2xl border border-slate-200/90 bg-white p-6 text-center shadow-sm">
          <p className="text-sm font-bold text-slate-900">Không tìm thấy pipeline</p>
          <p className="mt-1 text-xs text-slate-500">Pipeline này có thể đã bị xóa hoặc không tồn tại.</p>
          <Link href="/facebook" className="mt-4 inline-flex min-h-[44px] items-center gap-1.5 rounded-xl bg-indigo-600 px-4 py-2 text-sm font-bold text-white">
            ← Quay lại Facebook
          </Link>
        </div>
      </div>
    </Shell>
  );
}

export default async function FacebookPipelinePage({
  params,
  searchParams,
}: {
  params: Promise<{ pipelineId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { pipelineId } = await params;
  const sp = await searchParams;
  const tabRaw = typeof sp.tab === "string" ? sp.tab : "overview";
  const activeTab: FacebookTabKey = (TABS as string[]).includes(tabRaw) ? (tabRaw as FacebookTabKey) : "overview";

  // Real pipeline determines existence — never mock.
  let pipeline = null;
  try {
    pipeline = await getFacebookPipelineDetail(pipelineId);
  } catch (err) {
    if (err instanceof FacebookApiError && err.status === 404) {
      notFound();
    }
    return <MissingPipeline />;
  }
  if (!pipeline) {
    notFound();
  }

  // Tab data from backend_facebook. Each fetch degrades independently.
  const [sourcesRes, inventoryRes, destinationsRes, publicationsRes, flowRes, scheduleRes, scheduleFullRes] = await Promise.all([
    listFacebookSources(pipelineId).then(
      (v) => ({ ok: true as const, v }),
      (e) => ({ ok: false as const, e: e instanceof Error ? e.message : "Lỗi tải sources." }),
    ),
    listFacebookInventory(pipelineId, { limit: 50, offset: 0 }).then(
      (v) => ({ ok: true as const, v }),
      (e) => ({ ok: false as const, e: e instanceof Error ? e.message : "Lỗi tải inventory." }),
    ),
    listFacebookDestinations(pipelineId).then(
      (v) => ({ ok: true as const, v }),
      (e) => ({ ok: false as const, e: e instanceof Error ? e.message : "Lỗi tải destinations." }),
    ),
    listFacebookPublications(pipelineId, { limit: 100, offset: 0 }).then(
      (v) => ({ ok: true as const, v }),
      (e) => ({ ok: false as const, e: e instanceof Error ? e.message : "Lỗi tải publications." }),
    ),
    getFacebookFlowState(pipelineId).then(
      (v) => ({ ok: true as const, v }),
      (e) => ({ ok: false as const, e: e instanceof Error ? e.message : "Không tải được flow-state." }),
    ),
    getFacebookScheduleStatus(pipelineId).then(
      (v) => ({ ok: true as const, v }),
      (e) => ({ ok: false as const, e: e instanceof Error ? e.message : "Không tải được scheduler status." }),
    ),
    getFacebookSchedule(pipelineId).then(
      (v) => ({ ok: true as const, v }),
      (e) => ({ ok: false as const, e: e instanceof Error ? e.message : "Không tải được scheduler config." }),
    ),
  ]);

  const initialFlow: FacebookFlowState | null = flowRes.ok ? flowRes.v : null;
  const flowError: string | null = flowRes.ok ? null : flowRes.e;

  const initialSchedule: FacebookScheduleDto | null = scheduleFullRes.ok ? scheduleFullRes.v : null;

  // AI metadata stats + settings + one generated sample for the AI tab (server-side).
  let aiStats: Awaited<ReturnType<typeof getFacebookAiStats>> | null = null;
  let aiStatsError: string | null = null;
  let aiSample: Awaited<ReturnType<typeof getFacebookAiSample>> = null;
  let aiSettings: FacebookAiSettingsDto | null = null;
  try {
    const [statsData, sampleData, settingsData] = await Promise.all([
      getFacebookAiStats(pipelineId).catch(() => null),
      getFacebookAiSample(pipelineId).catch(() => null),
      getFacebookAiSettings(pipelineId).catch(() => null),
    ]);
    aiStats = statsData;
    aiSample = sampleData;
    aiSettings = settingsData;

    if (!aiSample && aiStats && aiStats.generated > 0 && inventoryRes.ok) {
      for (const item of inventoryRes.v.items) {
        const meta = await getFacebookReelAiMetadata(item.id).catch(() => null);
        if (meta && meta.status === "generated") {
          aiSample = meta;
          break;
        }
      }
    }
  } catch (err) {
    aiStatsError = err instanceof Error ? err.message : "Không tải được AI metadata.";
  }

  return (
    <Shell>
      <div className="w-full min-w-0">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <h1 className="truncate text-xl font-extrabold tracking-tight text-slate-900 sm:text-2xl">{pipeline.name}</h1>
            <p className="mt-1 text-xs text-slate-500 sm:text-sm">
              <span className="font-mono">/{pipeline.slug}</span>
              <span className="mx-1.5 text-slate-300">·</span>
              public
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Link href="/facebook" className="inline-flex min-h-[44px] items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 shrink-0">
              <IconBack size={15} />
              Facebook
            </Link>
            <span className={`inline-flex min-h-[44px] items-center gap-2 rounded-full px-3.5 py-2 text-sm font-bold shadow-sm ring-1 ring-inset ${
              pipeline.enabled
                ? "bg-emerald-600 text-white ring-emerald-500"
                : "bg-white text-slate-600 ring-slate-200"
            }`}>
              <span className={`h-2.5 w-2.5 rounded-full ${pipeline.enabled ? "bg-white" : "bg-slate-500"}`} />
              {pipeline.enabled ? "AUTO ON" : "AUTO OFF"}
            </span>
          </div>
        </div>

        <FacebookTabs pipelineId={pipelineId} activeTab={activeTab} />

        <div className="mt-4">
          {activeTab === "overview" ? (
            <FacebookOverview
              pipeline={pipeline}
              pipelineId={pipelineId}
              initialFlow={initialFlow}
              flowError={flowError}
            />
          ) : null}
          {activeTab === "sources" ? (
            sourcesRes.ok ? (
              <FacebookSources sources={sourcesRes.v} />
            ) : (
              <TabError message={sourcesRes.e} />
            )
          ) : null}
          {activeTab === "inventory" ? (
            inventoryRes.ok ? (
              <FacebookInventory
                pipelineId={pipelineId}
                initialItems={inventoryRes.v.items}
                initialTotal={inventoryRes.v.total}
              />
            ) : (
              <TabError message={inventoryRes.e} />
            )
          ) : null}
          {activeTab === "destinations" ? (
            destinationsRes.ok ? (
              <FacebookDestinations initial={destinationsRes.v} />
            ) : (
              <TabError message={destinationsRes.e} />
            )
          ) : null}
          {activeTab === "publications" ? (
            publicationsRes.ok ? (
              <FacebookPublications
                pipelineId={pipelineId}
                initialItems={publicationsRes.v.items}
                initialTotal={publicationsRes.v.total}
              />
            ) : (
              <TabError message={publicationsRes.e} />
            )
          ) : null}
          {activeTab === "ai-processing" ? (
            aiStats ? (
              <FacebookAiProcessing
                pipelineId={pipelineId}
                stats={aiStats}
                sample={aiSample}
                initialSettings={aiSettings}
              />
            ) : (
              <TabError message={aiStatsError ?? "Không tải được AI metadata."} />
            )
          ) : null}
          {activeTab === "scheduler" ? (
            scheduleRes.ok ? (
              <FacebookScheduler
                pipelineId={pipelineId}
                initialSchedule={initialSchedule}
                initialStatus={scheduleRes.v}
                destinationId={destinationsRes.ok ? destinationsRes.v[0]?.id ?? null : null}
              />
            ) : (
              <TabError message={scheduleRes.e} />
            )
          ) : null}
        </div>
      </div>
    </Shell>
  );
}

function TabError({ message }: { message: string }) {
  return (
    <div className="rounded-2xl border border-rose-200 bg-rose-50 p-6 text-center shadow-sm">
      <p className="text-sm font-bold text-rose-900">Không kết nối được backend Facebook</p>
      <p className="mt-1 text-xs text-rose-700">{message}</p>
    </div>
  );
}
