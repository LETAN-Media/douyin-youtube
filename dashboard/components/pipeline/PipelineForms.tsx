"use client";

import { ScheduleFields } from "./ScheduleFields";
import { useTransition } from "react";
import { useRouter } from "next/navigation";
import { useToast } from "@/components/Toast";
import { IconSettings, IconSparkles } from "@/components/icons";
/* Optimistic + single-tap: disable + spinner immediately, targeted refresh only. */
import { ConfirmButton } from "@/components/ConfirmButton";
import { Card, CardHeader, btnPrimary, inputCls, labelCls } from "@/components/ui";
import {
  actionDeletePipeline,
  actionUpdateAiProfile,
  actionUpdatePipelineSettings,
} from "@/lib/actions";
import type { Pipeline } from "@/lib/types";

export function AiProfileForm({
  pipelineId,
  pipeline,
}: {
  pipelineId: string;
  pipeline: Pipeline;
}) {
  const { toast } = useToast();
  const [pending, start] = useTransition();
  const router = useRouter();

  return (
    <Card>
      <CardHeader title="AI Profile" subtitle="Metadata generator dùng profile này cho mọi destination" icon={<IconSparkles size={16} />} />
      <form
        className="space-y-4 p-4 sm:px-5"
        onSubmit={(e) => {
          e.preventDefault();
          if (pending) return;
          const form = new FormData(e.currentTarget);
          start(async () => {
            const r = await actionUpdateAiProfile(pipelineId, form);
            toast(r.ok ? "Đã lưu AI profile." : r.error, r.ok ? "success" : "error");
            if (r.ok) router.refresh();
          });
        }}
      >
        <div>
          <label className={labelCls} htmlFor="ai-niche">Niche</label>
          <input id="ai-niche" name="niche" defaultValue={pipeline.niche ?? ""} className={inputCls} />
        </div>
        <div>
          <label className={labelCls} htmlFor="ai-lang">Language</label>
          <input id="ai-lang" name="language" defaultValue={pipeline.language ?? "en"} className={inputCls} />
        </div>
        <div>
          <label className={labelCls} htmlFor="ai-fixed">Preferred Hashtags (mỗi dòng 1 tag)</label>
          <textarea id="ai-fixed" name="fixed_hashtags" rows={3} defaultValue={(pipeline.fixed_hashtags ?? []).join("\n")} className={inputCls} />
        </div>
        <div>
          <label className={labelCls} htmlFor="ai-adaptive">Suggested Hashtags</label>
          <textarea id="ai-adaptive" name="adaptive_hashtags" rows={4} defaultValue={(pipeline.adaptive_hashtags ?? []).join("\n")} className={inputCls} />
        </div>
        <p className="text-xs text-slate-500">Hashtag chỉ là gợi ý. AI chọn lọc theo nội dung video, có thể tạo tag mới; tối đa 5 tag, không bắt buộc dùng đủ. Locked Hashtags trong Channel DNA là quy tắc riêng.</p>
        <div>
          <label className={labelCls} htmlFor="ai-prompt">Prompt profile</label>
          <textarea id="ai-prompt" name="prompt_profile" rows={5} defaultValue={pipeline.prompt_profile ?? ""} className={inputCls} />
        </div>
        <button type="submit" disabled={pending} className={btnPrimary}>
          {pending ? "Đang lưu…" : "Save AI Profile"}
        </button>
      </form>
    </Card>
  );
}

export function SettingsForm({
  pipelineId,
  pipeline,
}: {
  pipelineId: string;
  pipeline: Pipeline;
}) {
  const { toast } = useToast();
  const [pending, start] = useTransition();
  const router = useRouter();

  return (
    <Card>
      <CardHeader title="Settings" subtitle="Mặc định cho Destination không bật override; lịch đã Scheduled được giữ nguyên" icon={<IconSettings size={16} />} />
      <form
        className="grid gap-4 p-4 sm:grid-cols-2 sm:px-5"
        onSubmit={(e) => {
          e.preventDefault();
          if (pending) return;
          const form = new FormData(e.currentTarget);
          start(async () => {
            const r = await actionUpdatePipelineSettings(pipelineId, form);
            toast(r.ok ? "Đã lưu settings." : r.error, r.ok ? "success" : "error");
            if (r.ok) router.refresh();
          });
        }}
      >
        <div>
          <label className={labelCls} htmlFor="s-name">Name</label>
          <input id="s-name" name="name" defaultValue={pipeline.name} className={inputCls} />
        </div>
        <div>
          <label className={labelCls} htmlFor="s-privacy">Default privacy</label>
          <select id="s-privacy" name="default_privacy" defaultValue={pipeline.default_privacy} className={inputCls}>
            <option value="public">public</option>
            <option value="unlisted">unlisted</option>
            <option value="private">private</option>
          </select>
        </div>
        <ScheduleFields initial={pipeline}/>
        <div>
          <label className={labelCls} htmlFor="s-order">Backlog order</label>
          <select id="s-order" name="backlog_order" defaultValue={pipeline.backlog_order} className={inputCls}>
            <option value="asc">asc</option>
            <option value="desc">desc</option>
          </select>
        </div>
        <div>
          <label className={labelCls} htmlFor="s-threshold">Backlog threshold (days)</label>
          <input id="s-threshold" name="backlog_threshold_days" type="number" min={1} defaultValue={pipeline.backlog_threshold_days} className={inputCls} />
        </div>
        <div className="sm:col-span-2">
          <button type="submit" disabled={pending} className={btnPrimary}>
            {pending ? "Đang lưu…" : "Save Settings"}
          </button>
        </div>
      </form>
    </Card>
  );
}

export function DangerZone({
  pipelineId,
  name,
}: {
  pipelineId: string;
  name: string;
}) {
  const router = useRouter();
  return (
    <Card className="border-red-200">
      <CardHeader title="Danger zone" />
      <div className="flex flex-wrap items-center justify-between gap-3 p-4 sm:px-5">
        <p className="text-sm text-slate-600">
          Xóa pipeline <span className="font-semibold">{name}</span> và toàn bộ dữ liệu liên quan.
        </p>
        <ConfirmButton
          title="Xóa pipeline?"
          message={`Xóa pipeline "${name}"? Không thể hoàn tác.`}
          onConfirm={async () => {
            const r = await actionDeletePipeline(pipelineId);
            if (r.ok) router.push("/");
            return r;
          }}
        />
      </div>
    </Card>
  );
}
