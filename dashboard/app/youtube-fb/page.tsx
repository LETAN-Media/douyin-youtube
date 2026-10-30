import Link from "next/link";
import { Suspense } from "react";
import { Plus } from "lucide-react";

import { Shell } from "@/components/Shell";
import { ytFb, type YtFbPipeline } from "@/lib/youtube-fb-api";
import { YouTubeFbPipelineList } from "./YouTubeFbPipelineList";
import { YouTubeFbCreateForm } from "./YouTubeFbCreateForm";

export const dynamic = "force-dynamic";

export default async function YouTubeFbPage() {
  let pipelines: YtFbPipeline[] = [];
  let error: string | null = null;
  try {
    pipelines = await ytFb.listPipelines();
  } catch (err: any) {
    error = err?.message || "Không tải được pipelines.";
  }

  return (
    <Shell>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">YouTube → Facebook</h1>
        <Link
          href="/youtube-fb/new"
          className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
        >
          <Plus className="h-4 w-4" /> Tạo pipeline
        </Link>
      </div>
      {error ? (
        <p className="p-4 text-sm text-red-600">{error}</p>
      ) : (
        <Suspense fallback={<p className="p-4">Đang tải...</p>}>
          <YouTubeFbPipelineList initialPipelines={pipelines} />
        </Suspense>
      )}
    </Shell>
  );
}
