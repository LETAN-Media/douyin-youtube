import { Shell } from "@/components/Shell";
import { TIKTOK_PIPELINE_UPDATED_EVENT } from "@/components/tiktok/TikTokPipelineToggles";
import {
  listTikTokPipelines,
  TikTokPipelineDto,
  TikTokSummaryDto,
  TikTokApiError,
  getTikTokSummary,
} from "@/lib/tiktok-api";
import { TikTokPipelineList } from "./TikTokClient";

export default async function TikTokPage() {
  let pipelines: TikTokPipelineDto[] = [];
  let summaries: Record<string, TikTokSummaryDto> = {};
  let error: string | null = null;

  try {
    pipelines = await listTikTokPipelines();
    const rows = await Promise.all(
      pipelines.map(async (p) => {
        try {
          return [p.id, await getTikTokSummary(p.id)] as const;
        } catch {
          return null;
        }
      }),
    );
    for (const row of rows) {
      if (row) summaries[row[0]] = row[1];
    }
  } catch (err) {
    error = err instanceof TikTokApiError ? err.message : "Không tải được pipelines.";
  }

  return (
    <Shell>
      <TikTokPipelineList pipelines={pipelines} summaries={summaries} error={error} />
    </Shell>
  );
}

export { TIKTOK_PIPELINE_UPDATED_EVENT };
