import { Shell } from "@/components/Shell";
import { IconBack } from "@/components/icons";

export default function ChannelWorkspaceLoading() {
  return (
    <Shell>
      <div className="space-y-6">
        <div className="inline-flex min-h-[44px] items-center gap-1.5 rounded-lg px-2 py-1 text-sm font-semibold text-slate-400">
          <IconBack size={16} />
          Channels
        </div>

        {/* Header Skeleton */}
        <div className="rounded-2xl border border-indigo-200/40 bg-gradient-to-r from-indigo-50/40 via-white to-slate-50/50 p-5 shadow-sm animate-pulse">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-4">
              <div className="h-16 w-16 shrink-0 rounded-2xl bg-slate-200" />
              <div className="space-y-2">
                <div className="h-3 w-24 rounded-full bg-slate-200" />
                <div className="h-5 w-48 rounded-md bg-slate-200" />
                <div className="h-4 w-32 rounded-md bg-slate-200" />
              </div>
            </div>
            <div className="flex gap-2">
                <div className="h-10 w-24 rounded-xl bg-slate-200" />
                <div className="h-10 w-24 rounded-xl bg-slate-200" />
            </div>
          </div>
        </div>

        {/* Tabs Skeleton */}
        <div className="flex gap-2 border-b border-slate-200 overflow-x-auto pb-px animate-pulse">
          <div className="h-10 w-24 rounded-t-lg bg-slate-200" />
          <div className="h-10 w-24 rounded-t-lg bg-slate-200" />
          <div className="h-10 w-24 rounded-t-lg bg-slate-200" />
          <div className="h-10 w-24 rounded-t-lg bg-slate-200" />
        </div>

        {/* Content Skeleton */}
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4 animate-pulse">
          <div className="h-32 rounded-xl bg-slate-100" />
          <div className="h-32 rounded-xl bg-slate-100" />
          <div className="h-32 rounded-xl bg-slate-100" />
          <div className="h-32 rounded-xl bg-slate-100" />
        </div>
        
        <div className="animate-pulse h-64 rounded-xl bg-slate-100" />

        <div className="flex items-center justify-center p-8">
          <span className="flex items-center gap-2 text-sm font-semibold text-slate-500">
            <span className="h-5 w-5 animate-spin rounded-full border-2 border-slate-400 border-t-transparent" />
            Đang tải Workspace...
          </span>
        </div>
      </div>
    </Shell>
  );
}
