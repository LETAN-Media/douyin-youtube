import { Shell } from "@/components/Shell";
import { SkeletonCard, SkeletonList } from "@/components/ui";

export default function PipelineLoading() {
  return (
    <Shell>
      <div className="skeleton-bar h-5 w-24 rounded" />
      <div className="mt-2 flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="skeleton-bar h-7 w-48 rounded" />
          <div className="skeleton-bar mt-2 h-4 w-64 rounded" />
        </div>
        <div className="skeleton-bar h-9 w-28 rounded-xl" />
      </div>
      <div className="sticky top-14 z-30 -mx-4 mt-4 border-y border-slate-200 bg-[#f1f5f9]/95 px-4 sm:-mx-6 sm:px-6">
        <div className="mx-auto flex max-w-7xl gap-1 overflow-x-auto py-2">
          {Array.from({ length: 7 }).map((_, i) => (
            <div key={i} className="skeleton-bar h-[44px] w-24 shrink-0 rounded-xl" />
          ))}
        </div>
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
      </div>
      <div className="mt-3 rounded-2xl border border-slate-200 bg-white">
        <SkeletonList rows={5} />
      </div>
    </Shell>
  );
}
