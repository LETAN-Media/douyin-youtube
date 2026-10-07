import { Shell } from "@/components/Shell";
import { DramaApiError, getDramaSummary, listDramaPipelines } from "@/lib/drama-api";
import { DramaPipelineList } from "./DramaClient";

export default async function DramaPage() {
  let pipelines: Awaited<ReturnType<typeof listDramaPipelines>> = [];
  let summaries: Record<string, Awaited<ReturnType<typeof getDramaSummary>>> = {};
  let error: string | null = null;
  try {
    pipelines = await listDramaPipelines();
    const rows = await Promise.all(
      pipelines.map(async (p) => {
        try {
          return [p.id, await getDramaSummary(p.id)] as const;
        } catch {
          return null;
        }
      }),
    );
    for (const row of rows) {
      if (row) summaries[row[0]] = row[1];
    }
  } catch (err) {
    error = err instanceof DramaApiError ? err.message : "Không tải được pipelines.";
  }

  return (
    <Shell>
      <DramaPipelineList pipelines={pipelines} summaries={summaries} error={error} />
    </Shell>
  );
}