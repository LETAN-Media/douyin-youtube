import Link from "next/link";
import { Shell } from "@/components/Shell";
import { FacebookManualPublish } from "@/components/facebook/FacebookManualPublish";

export default function FacebookManualPage() {
  return (
    <Shell>
      <div className="w-full min-w-0">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <h1 className="truncate text-xl font-extrabold tracking-tight text-slate-900 sm:text-2xl">
              Manual Publish
            </h1>
            <p className="mt-1 text-xs text-slate-500 sm:text-sm">
              Đăng video Facebook lên YouTube, không qua Inventory/Scheduler
            </p>
          </div>
          <Link
            href="/facebook"
            className="inline-flex min-h-[44px] shrink-0 items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50"
          >
            ← Auto Pipelines
          </Link>
        </div>
        <div className="mt-4 flex gap-2">
          <Link
            href="/facebook"
            className="inline-flex min-h-[44px] items-center rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-bold text-slate-700 shadow-sm transition hover:bg-slate-50"
          >
            Auto Pipelines
          </Link>
          <span className="inline-flex min-h-[44px] items-center rounded-xl bg-indigo-600 px-4 py-2 text-xs font-bold text-white shadow-sm">
            Manual Publish
          </span>
        </div>
        <div className="mt-4">
          <FacebookManualPublish />
        </div>
      </div>
    </Shell>
  );
}
