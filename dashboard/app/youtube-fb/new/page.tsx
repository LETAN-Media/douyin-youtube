import { Shell } from "@/components/Shell";
import { YouTubeFbCreateForm } from "../YouTubeFbCreateForm";

export default function YouTubeFbNewPipelinePage() {
  return (
    <Shell>
      <div className="max-w-2xl">
        <h1 className="mb-4 text-xl font-semibold">Tạo pipeline mới</h1>
        <p className="mb-6 text-sm text-slate-600">
          Pipeline này quét video từ nguồn YouTube và xuất bản sang Fanpage Facebook theo lịch.
        </p>
        <YouTubeFbCreateForm />
      </div>
    </Shell>
  );
}
