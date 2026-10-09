"use client";

import { useEffect, useState } from "react";
import type { AudioPipelineDto } from "@/lib/audio-api";

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-2xl bg-white p-4 shadow-sm">{children}</div>
  );
}

function Overview({ pipeline }: { pipeline: AudioPipelineDto }) {
  const stats: [string, number | string][] = [
    ["Nguồn", pipeline.total_sources],
    ["Video chờ đăng", pipeline.pending_videos],
    ["Đã đăng", pipeline.published_videos],
    ["Job đang chạy", pipeline.running_jobs],
    ["Job lỗi", pipeline.failed_jobs],
    ["Auto publish", pipeline.auto_publish ? "ON" : "OFF"],
  ];
  return (
    <div className="space-y-3">
      <Card>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {stats.map(([label, value]) => (
            <div key={label} className="rounded-xl bg-slate-50 px-3 py-2 text-center">
              <p className="text-base font-extrabold text-slate-900">{value}</p>
              <p className="text-[11px] text-slate-500">{label}</p>
            </div>
          ))}
        </div>
        {pipeline.last_publish ? (
          <p className="mt-3 text-xs text-slate-500">
            Lần đăng gần nhất:{" "}
            <a href={pipeline.last_publish.youtube_url} target="_blank"
              rel="noreferrer" className="font-bold text-indigo-700">
              {pipeline.last_publish.youtube_url}
            </a>
          </p>
        ) : null}
      </Card>
    </div>
  );
}

function Sources({ pipeline }: { pipeline: AudioPipelineDto }) {
  const [urls, setUrls] = useState("");
  const [items, setItems] = useState<any[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function reload() {
    const res = await fetch(
      `/api/audio/pipelines/${encodeURIComponent(pipeline.id)}/sources`,
      { cache: "no-store" });
    if (res.ok) setItems((await res.json()).items ?? []);
  }

  useEffect(() => { void reload(); }, [pipeline.id]);

  async function handleAdd() {
    if (!urls.trim() || saving) return;
    setSaving(true);
    setMsg(null);
    try {
      const res = await fetch(
        `/api/audio/pipelines/${encodeURIComponent(pipeline.id)}/sources`,
        { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ urls }) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.message || data.error);
      setMsg(`Đã thêm ${data.added?.length ?? 0}, trùng ${data.existing?.length ?? 0}, lỗi ${data.invalid?.length ?? 0}. Quét nền đã bắt đầu.`);
      setUrls("");
      void reload();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Lỗi.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-3">
      <Card>
        <p className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
          Thêm nguồn Facebook (nhiều dòng)
        </p>
        <textarea
          value={urls}
          onChange={(e) => setUrls(e.target.value)}
          rows={4}
          placeholder={"https://www.facebook.com/sourceA/reels/\nhttps://www.facebook.com/sourceB/reels/"}
          className="mt-2 block w-full rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none focus:border-indigo-500"
        />
        <button
          type="button" onClick={() => void handleAdd()} disabled={saving}
          className="mt-2 inline-flex min-h-[44px] items-center rounded-xl bg-indigo-600 px-4 py-2 text-sm font-bold text-white disabled:opacity-50"
        >
          {saving ? "Đang thêm…" : "Thêm nguồn"}
        </button>
        {msg ? <p className="mt-2 text-xs font-semibold text-slate-600">{msg}</p> : null}
      </Card>
      {items.map((s) => (
        <Card key={s.id}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              <p className="truncate text-sm font-bold text-slate-900">
                {s.page_name ?? s.canonical_url}
              </p>
              <p className="truncate font-mono text-[11px] text-slate-400">
                {s.canonical_url}
              </p>
              {s.scan ? (
                <p className="text-[11px] text-slate-500">
                  Quét: {s.scan.state} · thấy {s.scan.found} · thêm {s.scan.added}
                  {s.scan.error ? ` · ${s.scan.error}` : ""}
                </p>
              ) : null}
            </div>
            <span className={`rounded-full px-2.5 py-1 text-[11px] font-bold ${
              s.enabled ? "bg-emerald-100 text-emerald-700" : "bg-slate-200 text-slate-600"
            }`}>
              {s.enabled ? "Bật" : "Tắt"}
            </span>
          </div>
        </Card>
      ))}
    </div>
  );
}

function Inventory({ pipeline }: { pipeline: AudioPipelineDto }) {
  const [status, setStatus] = useState("");
  const [items, setItems] = useState<any[]>([]);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    (async () => {
      const qs = status ? `?status=${encodeURIComponent(status)}` : "";
      const res = await fetch(
        `/api/audio/pipelines/${encodeURIComponent(pipeline.id)}/inventory${qs}`,
        { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        setItems(data.items ?? []);
        setTotal(data.total ?? 0);
      }
    })();
  }, [pipeline.id, status]);

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
          Inventory ({total})
        </p>
        <select
          value={status} onChange={(e) => setStatus(e.target.value)}
          className="min-h-[40px] rounded-xl border border-slate-200 px-2 text-xs"
        >
          <option value="">Tất cả</option>
          {["available", "reserved", "processing", "published", "failed", "skipped"].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>
      <ul className="mt-2 space-y-2">
        {items.slice(0, 50).map((it) => (
          <li key={it.id} className="rounded-xl bg-slate-50 px-3 py-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <a href={it.canonical_url} target="_blank" rel="noreferrer"
                className="min-w-0 flex-1 truncate font-mono text-[11px] text-indigo-700">
                {it.facebook_video_id ?? it.canonical_url}
              </a>
              <span className="rounded-full bg-slate-200 px-2 py-0.5 text-[11px] font-bold text-slate-600">
                {it.status}
              </span>
            </div>
            {it.caption ? (
              <p className="mt-1 line-clamp-2 text-xs text-slate-500">{it.caption}</p>
            ) : null}
          </li>
        ))}
      </ul>
    </Card>
  );
}

function Media({ pipeline }: { pipeline: AudioPipelineDto }) {
  const [kind, setKind] = useState("background");
  const [items, setItems] = useState<any[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  async function reload() {
    const res = await fetch(
      `/api/audio/pipelines/${encodeURIComponent(pipeline.id)}/media`,
      { cache: "no-store" });
    if (res.ok) setItems((await res.json()).items ?? []);
  }

  useEffect(() => { void reload(); }, [pipeline.id]);

  async function handleUpload() {
    if (!file || uploading) return;
    setUploading(true);
    setMsg(null);
    try {
      const form = new FormData();
      form.append("kind", kind);
      form.append("file", file);
      const res = await fetch(
        `/api/audio/pipelines/${encodeURIComponent(pipeline.id)}/media`,
        { method: "POST", body: form });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.message || data.error);
      setMsg("Upload thành công (GIF đã chuẩn hóa MP4 một lần).");
      setFile(null);
      void reload();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Upload lỗi.");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="space-y-3">
      <Card>
        <p className="text-xs font-extrabold uppercase tracking-wider text-slate-500">
          Upload media (GIF/MP4 nền, logo PNG/SVG, Template overlay)
        </p>
        <div className="mt-2 flex flex-col gap-2 sm:flex-row">
          <select
            value={kind} onChange={(e) => setKind(e.target.value)}
            className="min-h-[44px] rounded-xl border border-slate-200 px-2 text-sm"
          >
            <option value="background">Background</option>
            <option value="logo">Logo</option>
            <option value="template">Template overlay</option>
          </select>
          <label
            className="inline-flex min-h-[44px] flex-1 cursor-pointer items-center gap-2 overflow-hidden rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-600 hover:border-slate-300"
          >
            <span className="shrink-0 rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-bold text-slate-700">
              Chọn tệp
            </span>
            <span className="min-w-0 flex-1 truncate text-xs">
              {file ? file.name : "Chưa chọn tệp nào"}
            </span>
            <input
              type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="sr-only"
            />
          </label>
          <button
            type="button" onClick={() => void handleUpload()}
            disabled={!file || uploading}
            className="inline-flex min-h-[44px] items-center justify-center rounded-xl bg-indigo-600 px-4 py-2 text-sm font-bold text-white disabled:opacity-50"
          >
            {uploading ? "Đang tải…" : "Upload"}
          </button>
        </div>
        {msg ? <p className="mt-2 text-xs font-semibold text-slate-600">{msg}</p> : null}
      </Card>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {items.map((a) => (
          <div key={a.id} className="rounded-2xl bg-white p-2 shadow-sm">
            {a.preview_url && a.kind === "background" ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={a.preview_url} alt="" className="h-20 w-full rounded-xl object-cover" />
            ) : (
              <div className="flex h-20 items-center justify-center rounded-xl bg-slate-100 text-[11px] font-bold text-slate-500">
                {a.kind} · {a.file_name ?? a.id.slice(0, 8)}
              </div>
            )}
            <p className="mt-1 truncate text-[11px] text-slate-500">
              {(a.file_name ?? "").slice(0, 28)}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

function Processing({ pipeline }: { pipeline: AudioPipelineDto }) {
  const [form, setForm] = useState<Record<string, any> | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const res = await fetch(
        `/api/audio/pipelines/${encodeURIComponent(pipeline.id)}/processing-settings`,
        { cache: "no-store" });
      if (res.ok) setForm(await res.json());
    })();
  }, [pipeline.id]);

  async function save() {
    if (!form) return;
    const res = await fetch(
      `/api/audio/pipelines/${encodeURIComponent(pipeline.id)}/processing-settings`,
      { method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form) });
    setMsg(res.ok ? "Đã lưu." : "Lưu lỗi.");
    setTimeout(() => setMsg(null), 3000);
  }

  if (!form) return <Card><p className="text-xs text-slate-400">Đang tải…</p></Card>;
  const set = (k: string, v: any) => setForm({ ...form, [k]: v });

  return (
    <Card>
      <div className="space-y-3">
        <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" checked={!!form.normalize_audio} onChange={(e) => set("normalize_audio", e.target.checked)}
            className="h-4 w-4 rounded border-slate-300 text-indigo-600" />
          Chuẩn hóa âm lượng
        </label>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <p className="text-xs font-extrabold uppercase tracking-wider text-slate-500">Khung hình</p>
            <div className="mt-2 grid grid-cols-2 gap-2">
              {[["landscape", "16:9"], ["portrait", "9:16"]].map(([v, l]) => (
                <button key={v} type="button" onClick={() => set("orientation", v)}
                  className={`min-h-[44px] rounded-xl border text-xs font-bold ${
                    form.orientation === v ? "border-indigo-600 bg-indigo-50 text-indigo-700" : "border-slate-200 text-slate-600"
                  }`}>{l}</button>
              ))}
            </div>
          </div>
          <div>
            <p className="text-xs font-extrabold uppercase tracking-wider text-slate-500">Vị trí logo</p>
            <select value={form.logo_position ?? "top-right"} onChange={(e) => set("logo_position", e.target.value)}
              className="mt-2 block min-h-[44px] w-full rounded-xl border border-slate-200 px-2 text-sm">
              {["top-right", "top-left", "bottom-right", "bottom-left"].map((v) => (
                <option key={v} value={v}>{v}</option>
              ))}
            </select>
          </div>
        </div>
        <button type="button" onClick={() => void save()}
          className="inline-flex min-h-[44px] items-center rounded-xl bg-indigo-600 px-4 py-2 text-sm font-bold text-white">
          Lưu cài đặt
        </button>
        {msg ? <p className="text-xs font-bold text-emerald-600">{msg}</p> : null}
      </div>
    </Card>
  );
}

export function AudioTabA({
  pipeline, tab,
}: {
  pipeline: AudioPipelineDto;
  tab: string;
}) {
  if (tab === "sources") return <Sources pipeline={pipeline} />;
  if (tab === "inventory") return <Inventory pipeline={pipeline} />;
  if (tab === "media") return <Media pipeline={pipeline} />;
  if (tab === "processing") return <Processing pipeline={pipeline} />;
  return <Overview pipeline={pipeline} />;
}
