import { notFound } from "next/navigation";

import { Shell } from "@/components/Shell";
import { ytFb } from "@/lib/youtube-fb-api";
import { YouTubeFbPipelineDetail } from "../YouTubeFbPipelineDetail";

export const dynamic = "force-dynamic";

export default async function YouTubeFbPipelinePage({ params }: { params: Promise<{ pipelineId: string }> }) {
  const { pipelineId } = await params;
  const [pipeline, sources, videos, queue, history, pages, schedules] = await Promise.all([
    ytFb.getPipeline(pipelineId).catch(() => null),
    ytFb.listSources(pipelineId).catch(() => []),
    ytFb.listVideos(pipelineId).catch(() => []),
    ytFb.listQueue(pipelineId).catch(() => []),
    ytFb.listHistory(pipelineId).catch(() => []),
    ytFb.listFacebookPages(pipelineId).catch(() => []),
    ytFb.listSchedules(pipelineId).catch(() => []),
  ]);

  if (!pipeline) notFound();

  return (
    <Shell>
      <YouTubeFbPipelineDetail
        initialPipeline={pipeline}
        initialSources={sources}
        initialVideos={videos}
        initialQueue={queue}
        initialHistory={history}
        initialPages={pages}
        initialSchedules={schedules}
      />
    </Shell>
  );
}
