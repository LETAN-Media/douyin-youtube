"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Shell } from "@/components/Shell";
import { Card, btnPrimary, btnSecondary, inputCls, labelCls } from "@/components/ui";
import { useToast } from "@/components/Toast";
import { actionCreatePipeline } from "@/lib/actions";

export default function NewPipelinePage() {
  const router = useRouter();
  const { toast } = useToast();
  const [pending, start] = useTransition();

  return (
    <Shell>
      <div className="mx-auto max-w-2xl">
        <Link href="/" className="text-sm font-semibold text-indigo-600">
          ← Dashboard
        </Link>
        <h1 className="mt-2 text-xl font-bold text-slate-900">New Pipeline</h1>
        <Card className="mt-4 p-4 sm:p-6">
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
              <input id="upload_slots" name="upload_slots" defaultValue="08:00,11:00,14:00,17:00,20:00,23:00" className={inputCls} />
            </div>
            <div className="flex gap-2 pt-2">
              <Link href="/" className={`${btnSecondary} flex-1`}>Hủy</Link>
              <button type="submit" disabled={pending} className={`${btnPrimary} flex-1`}>
                {pending ? "Đang tạo…" : "Create"}
              </button>
            </div>
          </form>
        </Card>
      </div>
    </Shell>
  );
}
