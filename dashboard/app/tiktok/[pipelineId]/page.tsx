import Link from "next/link";
import { notFound } from "next/navigation";
import { Shell } from "@/components/Shell";
import { Badge, Card, CardHeader, btnPrimary, btnSmall } from "@/components/ui";
import { IconTikTok, IconUpload, IconVideo } from "@/components/icons";
import {
  getTikTokPipeline,
  getTikTokSummary,
  listTikTokDestinations,
  listTikTokSources,
  TikTokApiError,
  type TikTokDestinationDto,
  type TikTokSourceDto,
  type TikTokSummaryDto,
} from "@/lib/tiktok-api";
import { TikTokPipelineToggles } from "@/components/tiktok/TikTokPipelineToggles";

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

  try {
    pipeline = await getTikTokPipeline(pipelineId);
  } catch (err) {
    if (err instanceof TikTokApiError && err.status === 404) {
      notFound();
    }
    // Return friendly error
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
    const [summaryRes, sourcesRes, destsRes] = await Promise.all([
      getTikTokSummary(pipelineId).catch(() => null),
      listTikTokSources(pipelineId).catch(() => []),
      listTikTokDestinations(pipelineId).catch(() => []),
    ]);
    summary = summaryRes;
    sources = sourcesRes;
    destinations = destsRes;
  } catch {
    // Continue with partial data
  }

  return (
    <Shell>
      <div className="w-full min-w-0 space-y-6">
        {/* Header */}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Link
                href="/tiktok"
                className="text-xs font-semibold text-slate-500 hover:text-slate-700"
              >
                TikTok Pipelines
              </Link>
              <span className="text-slate-300">/</span>
              <span className="text-xs font-semibold text-slate-700">{pipeline.name}</span>
            </div>
            <h1 className="mt-1 text-2xl font-extrabold text-slate-900">
              {pipeline.name}
            </h1>
            <p className="text-xs text-slate-500">Slug: @{pipeline.slug}</p>
          </div>

          <div className="flex items-center gap-3">
            <Link
              href="/tiktok/manual"
              className="inline-flex min-h-[44px] items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50"
            >
              Manual Publish
            </Link>
            <TikTokPipelineToggles
              pipelineId={pipeline.id}
              initialEnabled={pipeline.enabled}
              initialAutoPublish={pipeline.auto_publish}
            />
          </div>
        </div>

        {/* Stats Grid */}
        {summary && (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Inventory
              </span>
              <p className="mt-1 text-2xl font-black text-slate-900">{summary.inventory}</p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Published
              </span>
              <p className="mt-1 text-2xl font-black text-indigo-600">{summary.published}</p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Queued
              </span>
              <p className="mt-1 text-2xl font-black text-amber-600">{summary.queued}</p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Failed
              </span>
              <p className="mt-1 text-2xl font-black text-rose-600">{summary.failed}</p>
            </div>
          </div>
        )}

        {/* YouTube Destinations */}
        <Card>
          <CardHeader
            title="Kênh YouTube đích (Destinations)"
            subtitle="Các kênh YouTube liên kết với pipeline này để nhận video tự động"
            icon={<IconUpload size={18} />}
          />
          <div className="p-4 sm:p-5">
            {destinations.length === 0 ? (
              <div className="rounded-xl border border-dashed border-slate-200 p-6 text-center text-sm text-slate-500">
                Chưa có kênh YouTube nào được cấu hình cho pipeline này.
                <div className="mt-3">
                  <Link href="/tiktok/manual" className={btnSmall}>
                    Vào Manual Publish để cấu hình kênh
                  </Link>
                </div>
              </div>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2">
                {destinations.map((d: any) => (
                  <div
                    key={d.id}
                    className="flex items-center justify-between rounded-xl border border-slate-200 bg-slate-50/50 p-4"
                  >
                    <div>
                      <p className="font-bold text-slate-900">{d.channel_name || "YouTube Channel"}</p>
                      <p className="text-xs text-slate-500">Mã kênh: {d.channel_id || d.id}</p>
                    </div>
                    {d.connected ? (
                      <Badge tone="green" dot>Đã liên kết</Badge>
                    ) : (
                      <Badge tone="amber">Chưa kết nối OAuth</Badge>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </Card>

        {/* Sources List */}
        <Card>
          <CardHeader
            title="Nguồn video TikTok (Sources)"
            subtitle="Các tài khoản hoặc creator TikTok được quét tự động"
            icon={<IconVideo size={18} />}
          />
          <div className="overflow-x-auto">
            {sources.length === 0 ? (
              <div className="p-6 text-center text-sm text-slate-500">
                Chưa có nguồn TikTok nào trong pipeline này.
              </div>
            ) : (
              <table className="w-full text-left text-sm text-slate-700">
                <thead className="border-b border-slate-100 bg-slate-50 text-xs uppercase text-slate-500">
                  <tr>
                    <th className="px-4 py-3">Creator / Username</th>
                    <th className="px-4 py-3">Trạng thái</th>
                    <th className="px-4 py-3">Đã tìm thấy</th>
                    <th className="px-4 py-3">Lần quét gần nhất</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {sources.map((s: any) => (
                    <tr key={s.id} className="hover:bg-slate-50/50">
                      <td className="px-4 py-3 font-semibold text-slate-900">
                        @{s.username}
                        {s.display_name && (
                          <span className="block text-xs font-normal text-slate-500">
                            {s.display_name}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {s.enabled ? (
                          <Badge tone="green" dot>Bật</Badge>
                        ) : (
                          <Badge tone="slate">Tắt</Badge>
                        )}
                      </td>
                      <td className="px-4 py-3 font-bold text-slate-900">
                        {s.discovered_total || 0} video
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-500">
                        {s.last_scan_at ? new Date(s.last_scan_at).toLocaleString("vi-VN") : "Chưa quét"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </Card>
      </div>
    </Shell>
  );
}
