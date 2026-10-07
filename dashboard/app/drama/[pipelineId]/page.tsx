import Link from "next/link";
import { notFound } from "next/navigation";
import { Shell } from "@/components/Shell";
import { IconBack } from "@/components/icons";
import {
  DramaApiError,
  getDramaPipelineDetail,
  getDramaSummary,
  listDramaSources,
  listDramaSeries,
  listDramaPipelineInventory,
  type DramaPipelineDto,
} from "@/lib/drama-api";
import { PipelineDetailClient, type DramaTabKey } from "./PipelineDetailClient";

const VALID_TABS: DramaTabKey[] = ["overview", "sources", "series", "inventory"];

export default async function DramaPipelinePage({
  params,
  searchParams,
}: {
  params: Promise<{ pipelineId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { pipelineId } = await params;
  const sp = await searchParams;
  const tabRaw = typeof sp.tab === "string" ? sp.tab : "overview";
  const activeTab: DramaTabKey = VALID_TABS.includes(tabRaw as DramaTabKey)
    ? (tabRaw as DramaTabKey)
    : "overview";

  let pipeline: DramaPipelineDto | null = null;
  let backendError: string | null = null;

  try {
    pipeline = await getDramaPipelineDetail(pipelineId);
  } catch (err) {
    if (err instanceof DramaApiError && err.status === 404) {
      notFound();
    }
    backendError = err instanceof Error ? err.message : "Không kết nối được backend Drama.";
  }

  if (!pipeline && !backendError) {
    notFound();
  }

  // If backend is unavailable (500/502/503/timeout), show a clear error page instead of fake 404
  if (backendError || !pipeline) {
    return (
      <Shell>
        <div className="w-full min-w-0">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <h1 className="truncate text-xl font-extrabold tracking-tight text-slate-900 sm:text-2xl">
                Drama Pipeline
              </h1>
              <p className="mt-1 font-mono text-xs text-slate-500 sm:text-sm">
                ID: {pipelineId}
              </p>
            </div>
            <Link
              href="/drama"
              className="inline-flex min-h-[44px] shrink-0 items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50"
            >
              <IconBack size={15} />
              Quay lại Drama
            </Link>
          </div>
          <div className="mt-6 rounded-2xl border border-rose-200 bg-rose-50 p-8 text-center shadow-sm sm:p-12">
            <h3 className="text-base font-extrabold text-rose-900">
              Không kết nối được backend Drama
            </h3>
            <p className="mx-auto mt-2 max-w-md text-xs leading-relaxed text-rose-700">
              {backendError}
            </p>
            <div className="mt-6 flex flex-wrap justify-center gap-3">
              <Link
                href="/drama"
                className="inline-flex min-h-[40px] items-center gap-1.5 rounded-xl bg-indigo-600 px-4 py-2 text-sm font-bold text-white shadow-sm transition hover:bg-indigo-500"
              >
                ← Quay lại danh sách Drama
              </Link>
            </div>
          </div>
        </div>
      </Shell>
    );
  }

  // Load initial tab data with graceful independent fallback
  const [summaryRes, sourcesRes, seriesRes, inventoryRes] = await Promise.all([
    getDramaSummary(pipelineId).then(
      (v) => ({ ok: true as const, v }),
      (e) => ({
        ok: false as const,
        e: e instanceof Error ? e.message : "Lỗi tải summary.",
      }),
    ),
    listDramaSources(pipelineId).then(
      (v) => ({ ok: true as const, v }),
      (e) => ({
        ok: false as const,
        e: e instanceof Error ? e.message : "Lỗi tải sources.",
      }),
    ),
    listDramaSeries(pipelineId).then(
      (v) => ({ ok: true as const, v }),
      (e) => ({
        ok: false as const,
        e: e instanceof Error ? e.message : "Lỗi tải series.",
      }),
    ),
    listDramaPipelineInventory(pipelineId, { limit: 500, offset: 0 }).then(
      (v) => ({ ok: true as const, v }),
      (e) => ({
        ok: false as const,
        e: e instanceof Error ? e.message : "Lỗi tải inventory.",
      }),
    ),
  ]);

  const initialSummary = summaryRes.ok
    ? summaryRes.v
    : {
        pipeline,
        sources: 0,
        series: 0,
        inventory: 0,
      };

  return (
    <Shell>
      <PipelineDetailClient
        pipeline={pipeline}
        initialSummary={initialSummary}
        summaryError={summaryRes.ok ? null : summaryRes.e}
        initialSources={sourcesRes.ok ? sourcesRes.v : []}
        sourcesError={sourcesRes.ok ? null : sourcesRes.e}
        initialSeries={seriesRes.ok ? seriesRes.v : []}
        seriesError={seriesRes.ok ? null : seriesRes.e}
        initialInventory={
          inventoryRes.ok ? inventoryRes.v : { items: [], total: 0 }
        }
        inventoryError={inventoryRes.ok ? null : inventoryRes.e}
        initialTab={activeTab}
      />
    </Shell>
  );
}
