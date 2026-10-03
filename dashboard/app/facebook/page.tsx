import { Shell } from "@/components/Shell";
import { PageHeader } from "@/components/ui";

export default function FacebookPage() {
  return (
    <Shell>
      <PageHeader
        title="Facebook"
        description="Quản lý và đăng nội dung Facebook"
      />
      <div className="mt-6">
        <div className="rounded-2xl border border-slate-200/90 bg-white p-6 shadow-sm sm:p-8">
          <div className="flex flex-col items-start gap-4 sm:flex-row sm:items-center sm:gap-5">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-slate-100 text-slate-600">
              <svg
                width="24"
                height="24"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden
              >
                <path d="M18 2h-3a5 5 0 0 0-5 5v3H7v4h3v8h4v-8h3l1-4h-4V7a1 1 0 0 1 1-1h3z" />
              </svg>
            </div>
            <div className="min-w-0">
              <h3 className="text-base font-extrabold text-slate-900">Facebook</h3>
              <p className="mt-1 text-xs text-slate-500 sm:text-sm">
                Tính năng Facebook đang được chuẩn bị.
              </p>
            </div>
          </div>
        </div>
      </div>
    </Shell>
  );
}
