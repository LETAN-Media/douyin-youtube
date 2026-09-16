import { Shell } from "@/components/Shell";
import { listChannels, listPipelines } from "@/lib/api";
import type { ChannelItem, Pipeline } from "@/lib/types";
import { ChannelsClient } from "./ChannelsClient";

export const dynamic = "force-dynamic";

export default async function ChannelsPage() {
  let channels: ChannelItem[] = [];
  let pipelines: Pipeline[] = [];

  try {
    channels = await listChannels();
  } catch (e) {
    console.error("Failed to load channels on server:", e);
  }

  try {
    pipelines = await listPipelines();
  } catch (e) {
    console.error("Failed to load pipelines on server:", e);
  }

  return (
    <Shell>
      <ChannelsClient
        initialChannels={channels}
        pipelines={pipelines}
      />
    </Shell>
  );
}
