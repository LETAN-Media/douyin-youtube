import Link from "next/link";
import { notFound } from "next/navigation";
import { Shell } from "@/components/Shell";
import { Card, CardHeader } from "@/components/ui";
import { IconBack, IconDestinations } from "@/components/icons";
import { getInventoryVideo, listDestinations } from "@/lib/api";
import { ApiError } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { StatusBadge } from "@/components/pipeline/InventoryPanel";
import { MatrixActions } from "@/components/pipeline/MatrixActions";

export const dynamic = "force-dynamic";

export default async function VideoDetailPage({
  params,
}: {
  params: Promise<{ pipelineId: string; videoId: string }>;
}) {
  const { pipelineId, videoId } = await params;

  let video;
  try {
    video = await getInventoryVideo(pipelineId, videoId);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    return (
      <Shell>
        <Card className="p-5">
          <p className="text-sm font-semibold text-red-700">Không tải được video</p>
          <p className="mt-1 text-sm text-slate-600">{e instanceof Error ? e.message : ""}</p>
        </Card>
      </Shell>
    );
  }

  const destinations = await listDestinations(pipelineId).catch(() => []);
  const pubByDest = new Map(video.publications.map((p) => [p.destination_id, p]));

  return (
    <Shell>
      <Link
        href={`/pipelines/${pipelineId}?tab=inventory`}
        className="inline-flex min-h-[44px] items-center gap-1.5 rounded-lg px-2 py-1 text-sm font-semibold text-slate-500 transition hover:bg-slate-200/60 hover:text-slate-800 sm:min-h-[32px]"
      >
        <IconBack size={15} />
        Inventory
      </Link>
      <Card className="mt-1 p-4 sm:px-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <h1 className="line-clamp-2 min-w-0 flex-1 text-lg font-extrabold tracking-tight text-slate-900">
            {video.title || video.video_id}
          </h1>
          <StatusBadge status={video.status} backlog={video.is_backlog} />
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500">
          <span>
            Source: <span className="font-bold text-slate-700">{video.source_name ?? "—"}</span>
          </span>
          <span className="text-slate-300">·</span>
          <a href={video.url} target="_blank" rel="noreferrer" className="font-bold text-indigo-600 hover:text-indigo-700">
            Open Douyin →
          </a>
        </div>
      </Card>

      <Card className="mt-4">
        <CardHeader
          title={`Publication matrix (${destinations.length} destinations)`}
          subtitle="Action áp dụng đúng destination, không ảnh hưởng destination khác"
          icon={<IconDestinations size={16} />}
        />
        {destinations.length === 0 ? (
          <p className="p-5 text-sm text-slate-500">Chưa có destination nào.</p>
        ) : (
          <div className="divide-y divide-slate-100">
            {destinations.map((d) => {
              const pub = pubByDest.get(d.id);
              return (
                <MatrixActions
                  key={d.id}
                  pipelineId={pipelineId}
                  videoId={video.id}
                  destination={d}
                  publication={pub ?? null}
                />
              );
            })}
          </div>
        )}
      </Card>

      <Card className="mt-4">
        <CardHeader title="Video info" />
        <dl className="space-y-2 p-4 text-sm sm:px-5">
          <div className="flex justify-between gap-3">
            <dt className="text-slate-500">Video ID</dt>
            <dd className="font-mono text-xs">{video.video_id}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-slate-500">Douyin created</dt>
            <dd>{formatDateTime(video.douyin_created_at)}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-slate-500">Scheduled</dt>
            <dd>{formatDateTime(video.scheduled_at)}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-slate-500">Published</dt>
            <dd>{formatDateTime(video.published_at)}</dd>
          </div>
          {video.description ? (
            <div>
              <dt className="text-slate-500">Description</dt>
              <dd className="mt-1 whitespace-pre-wrap break-words text-slate-700">{video.description.slice(0, 1000)}</dd>
            </div>
          ) : null}
        </dl>
      </Card>
    </Shell>
  );
}
