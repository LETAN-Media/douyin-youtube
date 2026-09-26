"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Shell } from "@/components/Shell";
import { Card, CardHeader, PageHeader, btnPrimary, btnSecondary, inputCls, labelCls } from "@/components/ui";
import { IconBack, IconPlus } from "@/components/icons";
import { useToast } from "@/components/Toast";
import { actionCreatePipeline } from "@/lib/actions";

export default function NewPipelinePage() {
  const router = useRouter();
  const { toast } = useToast();
  const [pending, start] = useTransition();

  return (
    <Shell>
      <div className="mx-auto max-w-2xl">
        <Link
          href="/"
          className="inline-flex min-h-[44px] items-center gap-1.5 rounded-lg px-2 py-1 text-sm font-semibold text-slate-500 transition hover:bg-slate-200/60 hover:text-slate-800 sm:min-h-[32px]"
        >
          <IconBack size={15} />
          Dashboard
        </Link>
        <div className="mt-1">
          <PageHeader
            eyebrow="Workspace"
            title="New Pipeline"
            description="Tạo pipeline để thu thập Douyin và phân phối đa nền tảng."
          />
        </div>
        <Card className="mt-4 overflow-hidden">
          <CardHeader
            title="Thông tin pipeline"
            subtitle="Tên và lịch mặc định — schedule chi tiết nằm ở từng destination"
            icon={<IconPlus size={16} />}
          />
          <div className="p-4 sm:p-6">
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              const form = new FormData(e.currentTarget);
              start(async () => {
                const r = await actionCreatePipeline(form);
                if (r.ok && r.id) {
                  toast("Đã tạo pipeline.", "success");
                  router.push(`/pipelines/${r.id}`);
                } else {
                  toast(r.ok ? "Đã tạo." : r.error, r.ok ? "success" : "error");
                }
              });
            }}
          >
            <div>
              <label className={labelCls} htmlFor="name">Name *</label>
              <input id="name" name="name" required className={inputCls} placeholder="Vibe Men World" />
            </div>
            <div>
              <label className={labelCls} htmlFor="slug">Slug (để trống = tự tạo)</label>
              <input id="slug" name="slug" className={inputCls} placeholder="vibe-men-world" />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className={labelCls} htmlFor="language">Language</label>
                <input id="language" name="language" defaultValue="en" className={inputCls} />
              </div>
              <div>
                <label className={labelCls} htmlFor="timezone">Timezone</label>
                <input id="timezone" name="timezone" defaultValue="Asia/Ho_Chi_Minh" className={inputCls} />
              </div>
            </div>
            <div>
              <label className={labelCls} htmlFor="niche">Niche</label>
              <input id="niche" name="niche" className={inputCls} placeholder="attractive men, fitness..." />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className={labelCls} htmlFor="default_privacy">Default privacy</label>
                <select id="default_privacy" name="default_privacy" defaultValue="public" className={inputCls}>
                  <option value="public">public</option>
                  <option value="unlisted">unlisted</option>
                  <option value="private">private</option>
                </select>
              </div>
              <div>
                <label className={labelCls} htmlFor="daily_upload_limit">Daily upload limit</label>
                <input id="daily_upload_limit" name="daily_upload_limit" type="number" min={1} max={50} defaultValue={6} className={inputCls} />
              </div>
            </div>
            <div>
              <label className={labelCls} htmlFor="upload_slots">Upload slots (cách nhau bằng dấu phẩy)</label>
              <input id="upload_slots" name="upload_slots" defaultValue="09:00,12:00,18:00,21:00" className={inputCls} />
              <p className="mt-1 text-[11px] text-slate-500">Ví dụ backlog 20 video với slots 09:00,18:00 → video1 Sep 26 09:00, video2 Sep 26 18:00, video3 Sep 27 09:00…</p>
            </div>
            <div>
              <label className={labelCls} htmlFor="publishing_strategy">Publishing strategy</label>
              <select id="publishing_strategy" name="publishing_strategy" defaultValue="immediate" className={inputCls}>
                <option value="immediate">A. Upload immediately</option>
                <option value="scheduled">B. YouTube scheduled publishing</option>
              </select>
            </div>
            <div className="flex gap-2 pt-2">
              <Link href="/" className={`${btnSecondary} flex-1`}>Hủy</Link>
              <button type="submit" disabled={pending} className={`${btnPrimary} flex-1`}>
                {pending ? "Đang tạo…" : "Create pipeline"}
              </button>
            </div>
          </form>
          </div>
        </Card>
      </div>
    </Shell>
  );
}
