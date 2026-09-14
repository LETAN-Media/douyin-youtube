import { Shell } from "@/components/Shell";
import { SkeletonCard, SkeletonList } from "@/components/ui";

export default function PipelineLoading() {
  return (
    <Shell>
      <div className="skeleton-bar h-5 w-24 rounded-lg" />
      <div className="mt-2 overflow-hidden rounded-2xl border border-slate-200/90 bg-white">
        <div className="skeleton-bar h-1.5 w-full" />
        <div className="flex items-center justify-between gap-3 p-4">
          <div className="flex min-w-0 flex-1 items-center gap-3">
            <div className="skeleton-bar h-12 w-12 shrink-0 rounded-2xl" />
            <div className="min-w-0 flex-1">
              <div className="skeleton-bar h-6 w-48 rounded-lg" />
              <div className="skeleton-bar mt-2 h-4 w-64 rounded-lg" />
            </div>
          </div>
          <div className="skeleton-bar h-10 w-28 rounded-xl" />
        </div>
      </div>
      <div className="mt-4 rounded-2xl border border-slate-200/90 bg-white/95 p-1.5">
        <div className="flex gap-1 overflow-x-auto">
          {Array.from({ length: 7 }).map((_, i) => (
            <div key={i} className="skeleton-bar h-[44px] w-24 shrink-0 rounded-xl sm:h-[38px]" />
          ))}
        </div>
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
      </div>
      <div className="mt-3 rounded-2xl border border-slate-200/90 bg-white">
        <SkeletonList rows={5} />
      </div>
    </Shell>
  );
}
