import { Shell } from "@/components/Shell";
import { ytFb, type YtFbPipeline } from "@/lib/youtube-fb-api";

export const dynamic = "force-dynamic";

export default async function YouTubeFbManualPage({
  searchParams,
}: {
  searchParams: Promise<{ pipeline?: string }>;
}) {
  const { pipeline: pipelineId } = await searchParams;
  let pipelines: YtFbPipeline[] = [];
  try {
    pipelines = await ytFb.listPipelines();
  } catch {
  }
  const selected = pipelineId && pipelines.find((p) => p.id === pipelineId);

  return (
    <Shell>
      <div className="max-w-3xl">
        <h1 className="mb-4 text-xl font-semibold">Đăng video thủ công</h1>
        <form action={submitManual} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-700">Pipeline</label>
            <select name="pipeline" required defaultValue={pipelineId || ""} className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
              <option value="">Chọn pipeline</option>
              {pipelines.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700">URL video YouTube</label>
            <input type="url" name="youtube_url" required placeholder="https://www.youtube.com/watch?v=..." className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700">Fanpage Facebook (row id)</label>
            <input type="text" name="facebook_page_id" required placeholder="page_..." className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700">Chế độ</label>
            <select name="publish_mode" defaultValue="reels_or_video" className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
              <option value="reels_or_video">Tự động (Reels hoặc Video)</option>
              <option value="reels">Reels</option>
              <option value="video">Video</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700">Caption / mô tả</label>
            <textarea name="caption" rows={3} className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
          </div>
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-1 text-sm">
              <input type="checkbox" name="use_ai_caption" defaultValue="true" defaultChecked /> Dùng AI sinh caption
            </label>
          </div>
          <button type="submit" className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700">
            Đăng ngay
          </button>
          {selected && (
            <p className="text-sm text-slate-500">Pipeline đã chọn: {selected.name} (AI: {selected.ai_strategy})</p>
          )}
        </form>
      </div>
    </Shell>
  );
}

async function submitManual(formData: FormData) {
  "use server";
  const pipeline = formData.get("pipeline")?.toString();
  if (!pipeline) return;
  const payload = {
    youtube_url: formData.get("youtube_url")?.toString() || "",
    facebook_page_id: formData.get("facebook_page_id")?.toString() || "",
    publish_mode: formData.get("publish_mode")?.toString() || "reels_or_video",
    caption: formData.get("caption")?.toString() || undefined,
    title: undefined,
    description: undefined,
    schedule_for: undefined,
    use_ai_caption: formData.get("use_ai_caption") !== null,
  };
  try {
    const result = await ytFb.manualPublish(pipeline, payload);
    console.log("manual publish result", result);
  } catch (err: any) {
    console.error(err?.message || err);
  }
}

void ytFb;
