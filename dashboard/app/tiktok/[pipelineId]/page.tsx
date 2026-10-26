import Link from "next/link";
import { notFound } from "next/navigation";
import { Shell } from "@/components/Shell";
import { btnPrimary } from "@/components/ui";
import {
  getTikTokAiSettings,
  getTikTokFlowState,
  getTikTokPipeline,
  getTikTokSchedule,
  getTikTokScheduleSlots,
  getTikTokSummary,
  listTikTokDestinations,
  listTikTokSources,
  TikTokApiError,
  type TikTokAiSettingsDto,
  type TikTokDestinationDto,
  type TikTokFlowState,
  type TikTokScheduleDto,
  type TikTokSlotDto,
  type TikTokSourceDto,
  type TikTokSummaryDto,
} from "@/lib/tiktok-api";
import { getChannelAvatarUrl } from "@/lib/youtube-avatar";
import { TikTokPipelineDetailClient } from "./TikTokPipelineDetailClient";

export default async function TikTokPipelineDetailPage({
  params,
}: {
  params: Promise<{ pipelineId: string }>;
}) {
  const { pipelineId } = await params;

  let pipeline;
  let summary: TikTokSummaryDto | null = null;
  let sources: TikTokSourceDto[] = [];
  let destinations: TikTokDestinationDto[] = [];
  let schedule: TikTokScheduleDto | null = null;
  let slots: TikTokSlotDto[] = [];
  let flow: TikTokFlowState | null = null;
  let flowError: string | null = null;
  let aiSettings: TikTokAiSettingsDto | null = null;
  let channelAvatarUrl: string | null = null;
  let channelName: string | null = null;

  try {
    pipeline = await getTikTokPipeline(pipelineId);
  } catch (err) {
    if (err instanceof TikTokApiError && err.status === 404) {
      notFound();
    }
    return (
      <Shell>
        <div className="rounded-2xl border border-rose-200 bg-rose-50 p-6 text-center">
          <p className="font-bold text-rose-700">Không thể tải pipeline TikTok</p>
          <p className="mt-1 text-sm text-rose-600">
            {err instanceof Error ? err.message : "Vui lòng kiểm tra lại cấu hình kết nối TikTok API."}
          </p>
          <Link href="/tiktok" className={`mt-4 inline-block ${btnPrimary}`}>
            ← Quay lại danh sách
          </Link>
        </div>
      </Shell>
    );
  }

  try {
    const [summaryRes, sourcesRes, destsRes, schedRes, slotsRes, flowRes, aiRes] = await Promise.all([
      getTikTokSummary(pipelineId).catch(() => null),
      listTikTokSources(pipelineId).catch(() => []),
      listTikTokDestinations(pipelineId).catch(() => []),
      getTikTokSchedule(pipelineId).catch(() => null),
      getTikTokScheduleSlots(pipelineId).catch(() => []),
      getTikTokFlowState(pipelineId).catch((err) => {
        flowError = err instanceof Error ? err.message : "Không tải được flow-state TikTok";
        return null;
      }),
      getTikTokAiSettings(pipelineId).catch(() => null),
    ]);
    summary = summaryRes;
    sources = sourcesRes;
    destinations = destsRes;
    schedule = schedRes;
    slots = slotsRes;
    flow = flowRes;
    aiSettings = aiRes;

    const connectedDest = destinations.find((d) => d.connected && d.is_default) || destinations.find((d) => d.connected);
    if (connectedDest) {
      channelName = connectedDest.channel_name || null;
      if (connectedDest.channel_avatar_url) {
        channelAvatarUrl = connectedDest.channel_avatar_url;
      } else if (connectedDest.channel_id) {
        channelAvatarUrl = await getChannelAvatarUrl(connectedDest.channel_id).catch(() => null);
      }
    }
  } catch {
    // Continue with partial data
  }

  return (
    <Shell>
      <TikTokPipelineDetailClient
        pipeline={pipeline}
        summary={summary}
        initialSources={sources}
        destinations={destinations}
        initialSchedule={schedule}
        initialSlots={slots}
        initialFlow={flow}
        flowError={flowError}
        initialAiSettings={aiSettings}
        channelAvatarUrl={channelAvatarUrl}
        channelName={channelName}
      />
    </Shell>
  );
}
