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
  const summaries: Record<string, TikTokSummaryDto> = {};
  const summaryErrors: Record<string, string> = {};
  let error: string | null = null;

  try {
    pipelines = await listTikTokPipelines();
    const rows = await Promise.all(
      pipelines.map(async (p) => {
        try {
          const sum = await getTikTokSummary(p.id);
          return { id: p.id, summary: sum, error: null };
        } catch (err) {
          const msg = err instanceof Error ? err.message : "Không tải được thống kê.";
          return { id: p.id, summary: null, error: msg };
        }
      }),
    );
    for (const row of rows) {
      if (row.summary) {
        summaries[row.id] = row.summary;
      } else if (row.error) {
        summaryErrors[row.id] = row.error;
      }
    }
  } catch (err) {
    error = err instanceof TikTokApiError ? err.message : "Không tải được pipelines.";
  }

  return (
    <Shell>
      <TikTokPipelineList
        pipelines={pipelines}
        summaries={summaries}
        summaryErrors={summaryErrors}
        error={error}
      />
    </Shell>
  );
}

export { TIKTOK_PIPELINE_UPDATED_EVENT };
