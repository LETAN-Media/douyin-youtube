import { Shell } from "@/components/Shell";
import { FacebookApiError, getFacebookSummary, listFacebookPipelines } from "@/lib/facebook-api";
import { FacebookPipelineList } from "./FacebookClient";

export default async function FacebookPage() {
  let pipelines: Awaited<ReturnType<typeof listFacebookPipelines>> = [];
  let summaries: Record<string, Awaited<ReturnType<typeof getFacebookSummary>>> = {};
  let error: string | null = null;
  try {
    pipelines = await listFacebookPipelines();
    const rows = await Promise.all(
      pipelines.map(async (p) => {
        try {
          return [p.id, await getFacebookSummary(p.id)] as const;
        } catch {
          return null;
        }
      }),
    );
    for (const row of rows) {
      if (row) summaries[row[0]] = row[1];
    }
  } catch (err) {
    error = err instanceof FacebookApiError ? err.message : "Không tải được pipelines.";
  }

  return (
    <Shell>
      <FacebookPipelineList pipelines={pipelines} summaries={summaries} error={error} />
    </Shell>
  );
}
