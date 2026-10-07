import Link from "next/link";
import { notFound } from "next/navigation";
import { Shell } from "@/components/Shell";
import {
  DramaApiError,
  getDramaPipelineDetail,
  getDramaSummary,
  listDramaSources,
  listDramaSeries,
  listDramaPipelineInventory,
} from "@/lib/drama-api";
import { PipelineDetailClient } from "./PipelineDetailClient";

export default async function PipelinePage({
  params,
}: {
  params: { pipelineId: string };
}) {
  const { pipelineId } = params;
  let pipeline;
  let summary;
  let sources;
  let series;
  let inventory;

  try {
    pipeline = await getDramaPipelineDetail(pipelineId);
    [summary, sources, series, inventory] = await Promise.all([
      getDramaSummary(pipelineId),
      listDramaSources(pipelineId),
      listDramaSeries(pipelineId),
      listDramaPipelineInventory(pipelineId, { limit: 10 }), // initial limit
    ]);
  } catch (err) {
    if (err instanceof DramaApiError && err.status === 404) {
      notFound();
    }
    throw err;
  }

  return (
    <Shell>
      <PipelineDetailClient
        pipeline={pipeline}
        summary={summary}
        sources={sources}
        series={series}
        inventory={inventory}
      />
    </Shell>
  );
}
