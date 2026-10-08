"use client";

import { useEffect, useState } from "react";
import type { AudioPipelineDto } from "@/lib/audio-api";

function Card({ children }: { children: React.ReactNode }) {
  return <div className="rounded-2xl bg-white p-4 shadow-sm">{children}</div>;
}

const LANGS = [
  ["vi", "VN — Tiếng Việt"],
  ["en", "EN — English"],
  ["zh", "ZH — 中文"],
];

function AiTab({ pipeline }: { pipeline: AudioPipelineDto }) {
  const [s, setS] = useState<any | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [preview, setPreview] = useState<any | null>(null);
  const [previewing, setPreviewing] = useState(false);

  async function reload() {
    const res = await fetch(
      `/api/audio/pipelines/${encodeURIComponent(pipeline.id)}/ai-settings`,
      { cache: "no-store" });
    if (res.ok) {
      const data = await res.json();
      setS({ ...data, locked: (data.locked_hashtags ?? []).join(", ") });
    }
  }

  useEffect(() => { void reload(); }, [pipeline.id]);
  if (!s) return <Card><p className="text-xs text-slate-400">Đang tải…</p></Card>;
  const set = (k: string, v: any) => setS({ ...s, [k]: v });

  async function save() {
    setSaving(true);
    setMsg(null);
    try {
      const res = await fetch(
        `/api/audio/pipelines/${encodeURIComponent(pipeline.id)}/ai-settings`,
        { method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            enabled: s.enabled, language: s.language, genre: s.genre || null,
            generate_title: s.generate_title,
            generate_description: s.generate_description,
            generate_hashtags: s.generate_hashtags,
            system_prompt: s.system_prompt?.trim() || null,
            title_template: s.title_template?.trim() || null,
            description_template: s.description_template?.trim() || null,
            locked_hashtags: s.locked?.trim() || null,
            expected_config_version: s.config_version ?? null,
          }) });
      const data = await res.json().catch(() => ({}));
      if (res.status === 409) throw new Error("Cài đặt đã đổi ở nơi khác, tải lại rồi lưu.");
      if (!res.ok) throw new Error(data.message || data.error);
      setS({ ...data, locked: (data.locked_hashtags ?? []).join(", ") });
      setMsg("Đã lưu.");
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Lưu lỗi.");
    } finally {
      setSaving(false);
      setTimeout(() => setMsg(null), 4000);
    }
  }

  async function reset() {
    if (!window.confirm("Khôi phục mặc định (tắt AI)?")) return;
    const res = await fetch(
      `/api/audio/pipelines/${encodeURIComponent(pipeline.id)}/ai-settings/reset`,
      { method: "POST" });
    if (res.ok) {
      const data = await res.json();
      setS({ ...data, locked: (data.locked_hashtags ?? []).join(", ") });
      setMsg("Đã khôi phục.");
      setTimeout(() => setMsg(null), 3000);
    }
  }

  async function doPreview() {
    setPreviewing(true);
    try {
      const inv = await fetch(
        `/api/audio/pipelines/${encodeURIComponent(pipeline.id)}/inventory?status=available`,
        { cache: "no-store" }).then((r) => r.json());
      const first = inv.items?.[0];
      const res = await fetch(
        `/api/audio/pipelines/${encodeURIComponent(pipeline.id)}/ai-metadata/preview`,
        { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ inventory_id: first?.id ?? null, language: s.language }) });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.message || data.error);
      setPreview(data);
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Preview lỗi.");
      setTimeout(() => setMsg(null), 4000);
    } finally {
      setPreviewing(false);
    }
  }

  return (
    <Card>
      <div className="space-y-3">
        <label className="flex cursor-pointer items-center justify-between gap-3">
          <span className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
            Bật AI Metadata
          </span>
          <input type="checkbox" checked={!!s.enabled} onChange={(e) => set("enabled", e.target.checked)}
            className="h-5 w-5 rounded border-slate-300 text-indigo-600" />
        </label>
        <div>
          <p className="text-xs font-extrabold uppercase tracking-wider text-slate-500">Ngôn ngữ</p>
          <div className="mt-2 grid grid-cols-3 gap-2">
            {LANGS.map(([v, l]) => (
              <button key={v} type="button" onClick={() => set("language", v)}
                className={`min-h-[44px] rounded-xl border px-2 text-xs font-bold ${
                  s.language === v ? "border-indigo-600 bg-indigo-50 text-indigo-700" : "border-slate-200 text-slate-600"
                }`}>{l}</button>
            ))}
          </div>
        </div>
        <div>
          <p className="text-xs font-extrabold uppercase tracking-wider text-slate-500">Thể loại</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {(s.genres ?? []).map((g: string) => (
              <button key={g} type="button" onClick={() => set("genre", g)}
                className={`rounded-full px-3 py-1.5 text-[11px] font-bold ${
                  s.genre === g ? "bg-indigo-600 text-white" : "bg-slate-100 text-slate-600"
                }`}>{g}</button>
            ))}
          </div>
          <input
            value={s.genre ?? ""} onChange={(e) => set("genre", e.target.value)}
            placeholder="Thể loại tùy chỉnh…"
            className="mt-2 block min-h-[44px] w-full rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none focus:border-indigo-500"
          />
        </div>
        {["generate_title", "generate_description", "generate_hashtags"].map((k) => (
          <label key={k} className="flex cursor-pointer items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={!!s[k]} onChange={(e) => set(k, e.target.checked)}
              className="h-4 w-4 rounded border-slate-300 text-indigo-600" />
            {k === "generate_title" ? "Tạo tiêu đề" : k === "generate_description" ? "Tạo mô tả" : "AI tự tạo hashtag"}
          </label>
        ))}
        <textarea
          value={s.system_prompt ?? ""} onChange={(e) => set("system_prompt", e.target.value)}
          rows={4} placeholder="System Prompt riêng của pipeline…"
          className="block w-full rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none focus:border-indigo-500"
        />
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <input
            value={s.title_template ?? ""} onChange={(e) => set("title_template", e.target.value)}
            placeholder="Mẫu tiêu đề: {title} | Truyện Audio Hay"
            className="block min-h-[44px] w-full rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none focus:border-indigo-500"
          />
          <input
            value={s.locked ?? ""} onChange={(e) => set("locked", e.target.value)}
            placeholder="Hashtag cố định: #AudioTruyen, #Hay"
            className="block min-h-[44px] w-full rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none focus:border-indigo-500"
          />
        </div>
        <textarea
          value={s.description_template ?? ""} onChange={(e) => set("description_template", e.target.value)}
          rows={3} placeholder="Mẫu mô tả: {description}&#10;{hashtags}"
          className="block w-full rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none focus:border-indigo-500"
        />
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={() => void save()} disabled={saving}
            className="inline-flex min-h-[44px] items-center rounded-xl bg-indigo-600 px-4 py-2 text-sm font-bold text-white disabled:opacity-50">
            {saving ? "Đang lưu…" : "Lưu cài đặt AI"}
          </button>
          <button type="button" onClick={() => void reset()}
            className="inline-flex min-h-[44px] items-center rounded-xl border border-slate-300 px-4 py-2 text-sm font-bold text-slate-600">
            Khôi phục mặc định
          </button>
          <button type="button" onClick={() => void doPreview()} disabled={previewing || !s.enabled}
            className="inline-flex min-h-[44px] items-center rounded-xl bg-slate-900 px-4 py-2 text-sm font-bold text-white disabled:opacity-50">
            {previewing ? "Đang tạo…" : "Tạo thử metadata"}
          </button>
        </div>
        {msg ? <p className="text-xs font-bold text-slate-600">{msg}</p> : null}
        {preview ? (
          <div className="space-y-1 rounded-xl bg-slate-50 p-3">
            <p className="text-[11px] text-slate-400">{preview.language?.toUpperCase()} · {preview.model}</p>
            <p className="text-sm font-bold text-slate-900">{preview.title}</p>
            <p className="whitespace-pre-wrap text-xs text-slate-600">{preview.description}</p>
            <p className="text-xs font-semibold text-indigo-700">{(preview.hashtags ?? []).join(" ")}</p>
          </div>
        ) : null}
      </div>
    </Card>
  );
}

function YoutubeTab({ pipeline }: { pipeline: AudioPipelineDto }) {
  const [dests, setDests] = useState<any[]>([]);
  const [msg, setMsg] = useState<string | null>(null);

  async function reload() {
    const res = await fetch(
      `/api/audio/pipelines/${encodeURIComponent(pipeline.id)}/youtube-destinations`,
      { cache: "no-store" });
    if (res.ok) setDests(await res.json());
  }

  useEffect(() => { void reload(); }, [pipeline.id]);

  async function connect() {
    const res = await fetch(
      `/api/audio/youtube/oauth/start?pipeline_id=${encodeURIComponent(pipeline.id)}`,
      { method: "POST" });
    const data = await res.json().catch(() => ({}));
    if (data.authorization_url) window.location.href = data.authorization_url;
    else setMsg(data.error || "Không bắt đầu được OAuth.");
  }

  return (
    <div className="space-y-3">
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
            Kênh YouTube đã kết nối
          </p>
          <button type="button" onClick={() => void connect()}
            className="inline-flex min-h-[44px] items-center rounded-xl bg-rose-600 px-4 py-2 text-sm font-bold text-white">
            + Kết nối YouTube
          </button>
        </div>
        {msg ? <p className="mt-2 text-xs font-semibold text-rose-600">{msg}</p> : null}
      </Card>
      {dests.length === 0 ? (
        <Card><p className="text-xs text-slate-500">Chưa kết nối kênh nào.</p></Card>
      ) : null}
      {dests.map((d) => (
        <Card key={d.id}>
          <div className="flex items-center gap-3">
            {d.channel_thumbnail ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={d.channel_thumbnail} alt="" className="h-10 w-10 rounded-full object-cover" />
            ) : null}
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-bold text-slate-900">
                {d.channel_title ?? d.channel_id ?? d.id}
              </p>
              <p className="text-[11px] text-slate-500">
                {d.connected ? "Đã kết nối" : "Đã ngắt kết nối"} · {d.visibility}
              </p>
            </div>
          </div>
        </Card>
      ))}
    </div>
  );
}

function SchedulerTab({ pipeline }: { pipeline: AudioPipelineDto }) {
  const [s, setS] = useState<any | null>(null);
  const [dests, setDests] = useState<any[]>([]);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const [a, b] = await Promise.all([
        fetch(`/api/audio/pipelines/${encodeURIComponent(pipeline.id)}/scheduler`, { cache: "no-store" }),
        fetch(`/api/audio/pipelines/${encodeURIComponent(pipeline.id)}/youtube-destinations`, { cache: "no-store" }),
      ]);
      if (a.ok) setS(await a.json());
      if (b.ok) setDests(await b.json());
    })();
  }, [pipeline.id]);

  if (!s) return <Card><p className="text-xs text-slate-400">Đang tải…</p></Card>;
  const set = (k: string, v: any) => setS({ ...s, [k]: v });

  async function save() {
    const res = await fetch(
      `/api/audio/pipelines/${encodeURIComponent(pipeline.id)}/scheduler`,
      { method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled: s.enabled, destination_id: s.destination_id,
          max_videos_per_day: Number(s.max_videos_per_day) || 3,
          min_gap_minutes: Number(s.min_gap_minutes) || 120,
          timezone: s.timezone, order_mode: s.order_mode,
          rotate_sources: s.rotate_sources,
        }) });
    setMsg(res.ok ? "Đã lưu lịch." : "Lưu lỗi.");
    setTimeout(() => setMsg(null), 3000);
  }

  return (
    <Card>
      <div className="space-y-3">
        <label className="flex cursor-pointer items-center justify-between gap-3">
          <span className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
            Auto Publish
          </span>
          <input type="checkbox" checked={!!s.enabled} onChange={(e) => set("enabled", e.target.checked)}
            className="h-5 w-5 rounded border-slate-300 text-indigo-600" />
        </label>
        <div>
          <p className="text-xs font-extrabold uppercase tracking-wider text-slate-500">Kênh đăng</p>
          <select value={s.destination_id ?? ""} onChange={(e) => set("destination_id", e.target.value || null)}
            className="mt-2 block min-h-[44px] w-full rounded-xl border border-slate-200 px-2 text-sm">
            <option value="">— Tự chọn kênh đã kết nối —</option>
            {dests.filter((d) => d.connected).map((d) => (
              <option key={d.id} value={d.id}>{d.channel_title ?? d.channel_id}</option>
            ))}
          </select>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <p className="text-xs font-extrabold uppercase tracking-wider text-slate-500">Tối đa/ngày</p>
            <input type="number" min={1} max={20} value={s.max_videos_per_day}
              onChange={(e) => set("max_videos_per_day", e.target.value)}
              className="mt-2 block min-h-[44px] w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" />
          </div>
          <div>
            <p className="text-xs font-extrabold uppercase tracking-wider text-slate-500">Cách nhau (phút)</p>
            <input type="number" min={15} value={s.min_gap_minutes}
              onChange={(e) => set("min_gap_minutes", e.target.value)}
              className="mt-2 block min-h-[44px] w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" />
          </div>
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <div>
            <p className="text-xs font-extrabold uppercase tracking-wider text-slate-500">Thứ tự</p>
            <select value={s.order_mode} onChange={(e) => set("order_mode", e.target.value)}
              className="mt-2 block min-h-[44px] w-full rounded-xl border border-slate-200 px-2 text-sm">
              <option value="oldest_first">Cũ trước</option>
              <option value="newest_first">Mới trước</option>
            </select>
          </div>
          <label className="flex cursor-pointer items-end gap-2 pb-2 text-sm text-slate-700">
            <input type="checkbox" checked={!!s.rotate_sources} onChange={(e) => set("rotate_sources", e.target.checked)}
              className="h-4 w-4 rounded border-slate-300 text-indigo-600" />
            Luân phiên nguồn
          </label>
        </div>
        <p className="text-xs text-slate-500">
          Trạng thái: {s.due ? "đến hạn" : "chờ"} ({s.due_reason})
          {s.next_run_at ? ` · chạy tiếp: ${s.next_run_at}` : ""}
        </p>
        <button type="button" onClick={() => void save()}
          className="inline-flex min-h-[44px] items-center rounded-xl bg-indigo-600 px-4 py-2 text-sm font-bold text-white">
          Lưu lịch
        </button>
        {msg ? <p className="text-xs font-bold text-emerald-600">{msg}</p> : null}
      </div>
    </Card>
  );
}

function ManualTab({ pipeline }: { pipeline: AudioPipelineDto }) {
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!url.trim() || busy) return;
    setBusy(true);
    setMsg(null);
    try {
      const res = await fetch(
        `/api/audio/pipelines/${encodeURIComponent(pipeline.id)}/manual`,
        { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ facebook_url: url.trim(), title: title.trim() || null }) });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.message || data.error);
      if (data.duplicate) setMsg(`Video đã đăng: ${data.youtube_url}`);
      else {
        setMsg(`Đã tạo job ${data.id}, worker sẽ xử lý.`);
        setUrl("");
        setTitle("");
      }
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Lỗi.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <div className="space-y-2">
        <p className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
          Đăng thủ công (URL bất kỳ, vẫn chống trùng)
        </p>
        <input
          value={url} onChange={(e) => setUrl(e.target.value)}
          placeholder="https://www.facebook.com/…/videos/…"
          className="block min-h-[44px] w-full rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none focus:border-indigo-500"
        />
        <input
          value={title} onChange={(e) => setTitle(e.target.value)}
          placeholder="Tiêu đề ghi đè (tùy chọn)"
          className="block min-h-[44px] w-full rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none focus:border-indigo-500"
        />
        <button type="button" onClick={() => void submit()} disabled={busy}
          className="inline-flex min-h-[44px] items-center rounded-xl bg-slate-900 px-4 py-2 text-sm font-bold text-white disabled:opacity-50">
          {busy ? "Đang tạo…" : "Tạo job thủ công"}
        </button>
        {msg ? <p className="text-xs font-semibold text-slate-600">{msg}</p> : null}
      </div>
    </Card>
  );
}

function HistoryTab({ pipeline }: { pipeline: AudioPipelineDto }) {
  const [items, setItems] = useState<any[]>([]);

  useEffect(() => {
    (async () => {
      const res = await fetch(
        `/api/audio/pipelines/${encodeURIComponent(pipeline.id)}/jobs`,
        { cache: "no-store" });
      if (res.ok) setItems((await res.json()).items ?? []);
    })();
  }, [pipeline.id]);

  return (
    <Card>
      <p className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
        Lịch sử jobs ({items.length})
      </p>
      <ul className="mt-2 space-y-2">
        {items.map((j) => (
          <li key={j.id} className="rounded-xl bg-slate-50 px-3 py-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-mono text-[11px] text-slate-500">{j.id}</span>
              <span className="text-[11px] font-bold text-slate-700">
                {j.status} · {j.stage} · {j.progress_percent}%
              </span>
            </div>
            {j.youtube_url ? (
              <a href={j.youtube_url} target="_blank" rel="noreferrer"
                className="text-[11px] font-bold text-indigo-700">{j.youtube_url}</a>
            ) : null}
            {j.last_error_code ? (
              <p className="text-[11px] font-semibold text-rose-600">
                {j.last_error_code}: {(j.last_error_message ?? "").slice(0, 200)}
              </p>
            ) : null}
          </li>
        ))}
      </ul>
    </Card>
  );
}

export function AudioTabB({
  pipeline, tab,
}: {
  pipeline: AudioPipelineDto;
  tab: string;
}) {
  if (tab === "ai") return <AiTab pipeline={pipeline} />;
  if (tab === "youtube") return <YoutubeTab pipeline={pipeline} />;
  if (tab === "scheduler") return <SchedulerTab pipeline={pipeline} />;
  if (tab === "manual") return <ManualTab pipeline={pipeline} />;
  if (tab === "history") return <HistoryTab pipeline={pipeline} />;
  return <AiTab pipeline={pipeline} />;
}
