import Link from "next/link";
import { notFound } from "next/navigation";
import { Shell } from "@/components/Shell";
import { Badge, Card, CardHeader, EmptyState } from "@/components/ui";
import { IconBack, IconClock, IconLink } from "@/components/icons";
import {
  getDestination,
  getDestinationStatus,
  getPipeline,
  getYoutubeStatus,
  listPublications,
} from "@/lib/api";
import { ApiError } from "@/lib/api";
import { formatDateTime, formatTime, platformLabel, publicationLabel } from "@/lib/format";
import { DestinationActions, DestinationEditForm } from "@/components/pipeline/DestinationDetail";

export const dynamic = "force-dynamic";

export default async function DestinationDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ pipelineId: string; destinationId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { pipelineId, destinationId } = await params;
  const sp = await searchParams;
  const oauth = typeof sp.oauth === "string" ? sp.oauth : undefined;

  let destination;
  try {
    destination = await getDestination(destinationId);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    return (
      <Shell>
        <Card className="p-5">
          <p className="text-sm font-semibold text-red-700">Không tải được destination</p>
          <p className="mt-1 text-sm text-slate-600">{e instanceof Error ? e.message : ""}</p>
        </Card>
      </Shell>
    );
  }

  const [pipeline, status, ytStatus, publications] = await Promise.all([
    getPipeline(pipelineId).catch(() => null),
    getDestinationStatus(destinationId).catch(() => null),
    destination.platform === "youtube"
      ? getYoutubeStatus(destinationId).catch(() => null)
      : Promise.resolve(null),
    listPublications({ pipeline_id: pipelineId, destination_id: destinationId, limit: 200 }).catch(
      () => [],
    ),
  ]);

  const isFacebook = destination.platform === "facebook";
  const connected = isFacebook ? false : (status?.connected ?? destination.connected);

  return (
    <Shell>
      <Link
        href={`/pipelines/${pipelineId}?tab=destinations`}
        className="inline-flex min-h-[44px] items-center gap-1.5 rounded-lg px-2 py-1 text-sm font-semibold text-slate-500 transition hover:bg-slate-200/60 hover:text-slate-800 sm:min-h-[32px]"
      >
        <IconBack size={15} />
        Destinations
      </Link>

      {oauth === "success" ? (
        <div className="mt-2 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-semibold text-emerald-900">
          YouTube OAuth thành công. Kiểm tra channel bên dưới.
        </div>
      ) : null}

      <Card className="mt-2 overflow-hidden p-0">
        <div className={`h-1.5 ${isFacebook ? "bg-gradient-to-r from-sky-500 to-blue-600" : "bg-gradient-to-r from-rose-500 to-red-500"}`} />
        <div className="flex flex-wrap items-start justify-between gap-3 p-4 sm:px-5">
          <div className="flex min-w-0 items-center gap-3">
            <span className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl text-lg font-black text-white ${isFacebook ? "bg-gradient-to-br from-sky-500 to-blue-600" : "bg-gradient-to-br from-rose-500 to-red-600"}`}>
              {destination.name.slice(0, 1).toUpperCase()}
            </span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="truncate text-xl font-extrabold tracking-tight text-slate-900">{destination.name}</h1>
                <Badge tone={platformLabel(destination.platform) === destination.platform ? "slate" : "indigo"}>
                  {platformLabel(destination.platform)}
                </Badge>
                {connected ? <Badge tone="green" dot>Connected</Badge> : <Badge tone="slate" dot>Not Connected</Badge>}
                {destination.enabled ? <Badge tone="green">Enabled</Badge> : <Badge tone="amber">Paused</Badge>}
              </div>
              <p className="mt-0.5 truncate text-[13px] text-slate-500">
                Pipeline: <span className="font-semibold text-slate-700">{pipeline?.name ?? pipelineId}</span>
                <span className="mx-1.5 text-slate-300">·</span>
                {destination.daily_upload_limit}/day
                <span className="mx-1.5 text-slate-300">·</span>
                {destination.timezone}
              </p>
            </div>
          </div>
          <DestinationActions pipelineId={pipelineId} destination={destination} isFacebook={isFacebook} connected={connected} />
        </div>
      </Card>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Connection" subtitle={isFacebook ? "Facebook adapter" : "YouTube OAuth theo destination_id"} icon={<IconLink size={16} />} />
          <div className="space-y-2 p-4 text-sm sm:px-5">
            {isFacebook ? (
              <p className="rounded-xl bg-amber-50 px-3 py-2.5 font-medium text-amber-800">
                Facebook publishing adapter not configured
              </p>
            ) : (
              <>
                <Row label="Channel title" value={destination.external_account_name ?? ytStatus?.channel_title ?? "—"} />
                <Row label="Channel ID" value={destination.external_account_id ?? ytStatus?.channel_id ?? "—"} />
                <Row label="Connected" value={connected ? "yes" : "no"} />
              </>
            )}
            <Row label="Strategy" value={destination.publish_strategy} />
            <Row label="Metadata" value={`${destination.metadata_language ?? "—"} / ${destination.metadata_profile ?? "—"}`} />
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Schedule"
            subtitle={`Today ${status?.today_published ?? 0}/${destination.daily_upload_limit}`}
            icon={<IconClock size={16} />}
          />
          <div className="p-4 sm:px-5">
            <div className="flex flex-wrap gap-1.5">
              {(destination.upload_slots ?? []).map((s) => (
                <span key={s} className="rounded-lg bg-slate-100 px-2.5 py-1 font-mono text-xs font-semibold text-slate-700">
                  {s}
                </span>
              ))}
            </div>
            <p className="mt-3 text-sm text-slate-600">
              Next slot: <span className="font-semibold">{status?.next_upload ? formatTime(status.next_upload) : "—"}</span>
              {" · "}Timezone: <span className="font-semibold">{destination.timezone}</span>
            </p>
          </div>
        </Card>
      </div>

      <Card className="mt-4">
        <CardHeader title={`Publications (${publications.length})`} subtitle="Chỉ publications của destination này" />
        {publications.length === 0 ? (
          <EmptyState title="Chưa có publication" />
        ) : (
          <div className="divide-y divide-slate-100">
            {publications.slice(0, 50).map((p) => {
              const label = publicationLabel(p.status);
              return (
                <div key={p.id} className="flex flex-wrap items-center gap-2 px-4 py-2.5 text-sm sm:px-5">
                  <Badge tone={label.tone}>{label.text}</Badge>
                  <span className="text-xs text-slate-500">{formatDateTime(p.scheduled_at)}</span>
                  {p.error ? <span className="w-full truncate text-xs text-red-600">{p.error}</span> : null}
                  {p.external_url ? (
                    <a href={p.external_url} target="_blank" rel="noreferrer" className="ml-auto text-xs font-semibold text-indigo-600">
                      Open →
                    </a>
                  ) : null}
                </div>
              );
            })}
          </div>
        )}
      </Card>

      <div className="mt-4">
        <DestinationEditForm pipelineId={pipelineId} destination={destination} />
      </div>
    </Shell>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-slate-500">{label}</dt>
      <dd className="min-w-0 truncate text-right font-semibold text-slate-900">{value}</dd>
    </div>
  );
}
