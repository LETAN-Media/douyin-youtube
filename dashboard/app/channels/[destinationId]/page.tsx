import { notFound } from "next/navigation";
import { Shell } from "@/components/Shell";
import { Card } from "@/components/ui";
import { getChannelDetail, ApiError } from "@/lib/api";
import type { ChannelDetail } from "@/lib/types";
import { ChannelWorkspaceClient } from "./ChannelWorkspaceClient";

export const dynamic = "force-dynamic";

export default async function ChannelDetailPage({
  params,
}: {
  params: Promise<{ destinationId: string }>;
}) {
  const { destinationId } = await params;

  let detail: ChannelDetail;
  try {
    detail = await getChannelDetail(destinationId);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      notFound();
    }
    return (
      <Shell>
        <Card className="p-6">
          <p className="text-sm font-bold text-rose-700">Không tải được thông tin kênh</p>
          <p className="mt-1 text-xs text-slate-600">
            {e instanceof Error ? e.message : "Đã xảy ra lỗi"}
          </p>
        </Card>
      </Shell>
    );
  }

  return (
    <Shell>
      <ChannelWorkspaceClient initialDetail={detail} />
    </Shell>
  );
}
