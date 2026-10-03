import Link from "next/link";
import { notFound } from "next/navigation";
import { Shell } from "@/components/Shell";
import { Badge } from "@/components/ui";
import { IconBack } from "@/components/icons";
import {
  getFacebookPipeline,
  getFacebookSources,
  getFacebookInventory,
  getFacebookPublications,
  getFacebookAiSettings,
} from "@/lib/facebook-mock";
import { FacebookTabs, type FacebookTabKey } from "@/components/facebook/FacebookTabs";
import { FacebookOverview } from "@/components/facebook/FacebookOverview";
import { FacebookSources } from "@/components/facebook/FacebookSources";
import { FacebookInventory } from "@/components/facebook/FacebookInventory";
import { FacebookDestinations } from "@/components/facebook/FacebookDestinations";
import { FacebookPublications } from "@/components/facebook/FacebookPublications";
import { FacebookAiProcessing } from "@/components/facebook/FacebookAiProcessing";

const TABS: FacebookTabKey[] = [
  "overview",
  "sources",
  "inventory",
  "destinations",
  "publications",
  "ai-processing",
];

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

  const pipeline = getFacebookPipeline(pipelineId);
  if (!pipeline) {
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

  const sources = getFacebookSources(pipelineId);
  const inventory = getFacebookInventory(pipelineId);
  const publications = getFacebookPublications(pipelineId);
  const aiSettings = getFacebookAiSettings(pipelineId);

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
            <FacebookOverview pipeline={pipeline} />
          ) : null}
          {activeTab === "sources" ? (
            <FacebookSources sources={sources} />
          ) : null}
          {activeTab === "inventory" ? (
            <FacebookInventory items={inventory} />
          ) : null}
          {activeTab === "destinations" ? (
            <FacebookDestinations pipelineId={pipelineId} />
          ) : null}
          {activeTab === "publications" ? (
            <FacebookPublications publications={publications} />
          ) : null}
          {activeTab === "ai-processing" ? (
            <FacebookAiProcessing settings={aiSettings} />
          ) : null}
        </div>
      </div>
    </Shell>
  );
}
