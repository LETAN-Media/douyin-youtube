"use client";

import { useCallback, useEffect, useState } from "react";

interface DNA {
  primary_niche?: string | null;
  secondary_topics?: string[];
  audience_profile?: string | null;
  target_language?: string | null;
  target_regions?: string[];
  content_style?: string | null;
  title_style?: string | null;
  title_patterns?: string[];
  core_keywords?: string[];
  locked_hashtags?: string[];
  locked_tags?: string[];
  winning_topics?: string[];
  weak_topics?: string[];
  avoid_topics?: string[];
  updated_at?: string | null;
}

interface Suggestion {
  id: string;
  kind: string;
  payload: Record<string, unknown>;
  reason?: string | null;
  status: string;
  created_at?: string | null;
}

function Chip({ label, locked, onRemove }: { label: string; locked?: boolean; onRemove?: () => void }) {
  return (
    <span className="inline-flex min-h-[32px] items-center gap-1 rounded-full bg-slate-100 px-2.5 py-1 font-mono text-[11px] font-bold text-slate-700">
      {label}
      {locked ? <span title="Locked">🔒</span> : null}
      {onRemove ? (
        <button type="button" onClick={onRemove} className="ml-0.5 font-black text-slate-400 hover:text-rose-600" aria-label={`Remove ${label}`}>
          ×
        </button>
      ) : null}
    </span>
  );
}

export function ChannelDNA({ destinationId }: { destinationId: string }) {
  const [dna, setDna] = useState<DNA | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [newTag, setNewTag] = useState("");
  const [newKw, setNewKw] = useState("");
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/channels/${destinationId}/dna`);
      if (res.ok) {
        const body = await res.json();
        setDna(body.dna);
      }
      const sres = await fetch(`/api/channels/${destinationId}/dna/suggestions?status=pending`);
      if (sres.ok) {
        const sbody = await sres.json();
        setSuggestions(Array.isArray(sbody.items) ? sbody.items : []);
      }
    } catch {
      /* noop */
    } finally {
      setLoading(false);
    }
  }, [destinationId]);

  useEffect(() => {
    load();
  }, [load]);

  const save = async () => {
    if (!dna) return;
    setSaving(true);
    setNotice(null);
    try {
      const res = await fetch(`/api/channels/${destinationId}/dna`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(dna),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || "Lưu DNA thất bại");
      setDna(body.dna);
      setNotice("Đã Save & Lock DNA của kênh này.");
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Lưu thất bại");
    } finally {
      setSaving(false);
    }
  };

  const aiSuggest = async (kind: "suggest-hashtags" | "suggest-tags") => {
    setBusy(kind);
    try {
      const res = await fetch(`/api/channels/${destinationId}/dna/${kind}`, { method: "POST" });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || "AI suggest thất bại");
      const list: string[] = Array.isArray(body.suggestions)
        ? body.suggestions.map((s: unknown) => (typeof s === "string" ? s : String((s as Record<string, unknown>).tag ?? ""))).filter(Boolean)
        : [];
      setNotice(list.length > 0 ? `AI gợi ý: ${list.slice(0, 8).join(", ")} — bấm Save & Lock để áp dụng.` : "AI chưa có gợi ý mới.");
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "AI suggest thất bại");
    } finally {
      setBusy(null);
    }
  };

  const collectPerf = async () => {
    setBusy("perf");
    try {
      const res = await fetch(`/api/channels/${destinationId}/dna/performance/collect`, { method: "POST" });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Collect thất bại");
      }
      setNotice("Đang thu thập performance nền — suggestions mới sẽ hiện sau vài phút.");
      setTimeout(load, 20000);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Collect thất bại");
    } finally {
      setBusy(null);
    }
  };

  const decide = async (id: string, action: "apply" | "dismiss") => {
    setBusy(id);
    try {
      const res = await fetch(`/api/channels/${destinationId}/dna/suggestions/${id}/${action}`, { method: "POST" });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Thao tác thất bại");
      }
      await load();
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Thao tác thất bại");
    } finally {
      setBusy(null);
    }
  };

  const set = (patch: Partial<DNA>) => setDna((prev) => ({ ...(prev ?? {}), ...patch }));

  return (
    <div className="w-full max-w-full space-y-3 overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-extrabold text-slate-900">Channel DNA</h3>
        <div className="flex flex-wrap gap-1.5">
          <button type="button" onClick={collectPerf} disabled={busy === "perf"}
            className="min-h-[36px] rounded-lg border border-slate-200 bg-white px-2.5 text-[11px] font-bold text-slate-700 disabled:opacity-50">
            {busy === "perf" ? "…" : "Collect performance"}
          </button>
          <button type="button" onClick={save} disabled={saving}
            className="min-h-[36px] rounded-lg bg-indigo-600 px-3 text-[11px] font-bold text-white disabled:opacity-50">
            {saving ? "Đang lưu…" : "Save & Lock"}
          </button>
        </div>
      </div>

      {notice ? <p className="rounded-lg bg-slate-50 px-3 py-2 text-[11px] font-semibold text-slate-600">{notice}</p> : null}
      {loading && !dna ? (
        <p className="py-6 text-center text-xs text-slate-400">Đang tải DNA…</p>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <label className="block">
              <span className="text-[11px] font-bold text-slate-600">Primary niche</span>
              <input value={dna?.primary_niche ?? ""} onChange={(e) => set({ primary_niche: e.target.value })}
                className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" />
            </label>
            <label className="block">
              <span className="text-[11px] font-bold text-slate-600">Target language</span>
              <input value={dna?.target_language ?? ""} onChange={(e) => set({ target_language: e.target.value })}
                placeholder="en / vi / auto" className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" />
            </label>
          </div>

          <label className="block">
            <span className="text-[11px] font-bold text-slate-600">Audience profile</span>
            <textarea value={dna?.audience_profile ?? ""} onChange={(e) => set({ audience_profile: e.target.value })} rows={2}
              className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-xs" />
          </label>

          <div className="rounded-xl border border-slate-200 bg-white p-3">
            <div className="flex items-center justify-between gap-2">
              <p className="text-[11px] font-extrabold text-slate-700">CORE HASHTAGS (locked — AI giữ nguyên)</p>
              <button type="button" onClick={() => aiSuggest("suggest-hashtags")} disabled={busy === "suggest-hashtags"}
                className="rounded-lg border border-slate-200 px-2 py-1 text-[11px] font-bold text-slate-700 disabled:opacity-50">
                {busy === "suggest-hashtags" ? "…" : "AI Suggest"}
              </button>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {(dna?.locked_hashtags ?? []).map((h) => (
                <Chip key={h} label={h} locked onRemove={() => set({ locked_hashtags: (dna?.locked_hashtags ?? []).filter((x) => x !== h) })} />
              ))}
            </div>
            <div className="mt-2 flex gap-1.5">
              <input value={newTag} onChange={(e) => setNewTag(e.target.value)} placeholder="#hashtag"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && newTag.trim()) {
                    e.preventDefault();
                    const v = newTag.trim().startsWith("#") ? newTag.trim() : `#${newTag.trim()}`;
                    set({ locked_hashtags: [...(dna?.locked_hashtags ?? []), v] });
                    setNewTag("");
                  }
                }}
                className="min-w-0 flex-1 rounded-lg border border-slate-200 px-2.5 py-1.5 font-mono text-xs" />
              <button type="button"
                onClick={() => {
                  if (!newTag.trim()) return;
                  const v = newTag.trim().startsWith("#") ? newTag.trim() : `#${newTag.trim()}`;
                  set({ locked_hashtags: [...(dna?.locked_hashtags ?? []), v] });
                  setNewTag("");
                }}
                className="rounded-lg bg-slate-900 px-3 py-1.5 text-[11px] font-bold text-white">
                + Add
              </button>
            </div>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-3">
            <div className="flex items-center justify-between gap-2">
              <p className="text-[11px] font-extrabold text-slate-700">CORE YOUTUBE TAGS (locked)</p>
              <button type="button" onClick={() => aiSuggest("suggest-tags")} disabled={busy === "suggest-tags"}
                className="rounded-lg border border-slate-200 px-2 py-1 text-[11px] font-bold text-slate-700 disabled:opacity-50">
                {busy === "suggest-tags" ? "…" : "AI Suggest"}
              </button>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {(dna?.locked_tags ?? []).map((t) => (
                <Chip key={t} label={t} locked onRemove={() => set({ locked_tags: (dna?.locked_tags ?? []).filter((x) => x !== t) })} />
              ))}
            </div>
            <div className="mt-2 flex gap-1.5">
              <input value={newKw} onChange={(e) => setNewKw(e.target.value)} placeholder="core tag keyword"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && newKw.trim()) {
                    e.preventDefault();
                    set({ locked_tags: [...(dna?.locked_tags ?? []), newKw.trim().toLowerCase()] });
                    setNewKw("");
                  }
                }}
                className="min-w-0 flex-1 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs" />
              <button type="button"
                onClick={() => {
                  if (!newKw.trim()) return;
                  set({ locked_tags: [...(dna?.locked_tags ?? []), newKw.trim().toLowerCase()] });
                  setNewKw("");
                }}
                className="rounded-lg bg-slate-900 px-3 py-1.5 text-[11px] font-bold text-white">
                + Add
              </button>
            </div>
          </div>

          {suggestions.length > 0 ? (
            <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-3">
              <p className="text-[11px] font-extrabold text-amber-900">Learning suggestions (cần admin xác nhận — locked không tự đổi)</p>
              <div className="mt-2 space-y-1.5">
                {suggestions.map((s) => (
                  <div key={s.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-white px-2.5 py-1.5">
                    <p className="min-w-0 flex-1 text-[11px] text-slate-700">
                      <span className="font-bold">{s.kind}</span>: {JSON.stringify(s.payload).slice(0, 120)}
                      {s.reason ? <span className="text-slate-500"> — {s.reason}</span> : null}
                    </p>
                    <div className="flex gap-1.5">
                      <button type="button" onClick={() => decide(s.id, "apply")} disabled={busy === s.id}
                        className="rounded-lg bg-emerald-600 px-2 py-1 text-[11px] font-bold text-white disabled:opacity-50">
                        Apply
                      </button>
                      <button type="button" onClick={() => decide(s.id, "dismiss")} disabled={busy === s.id}
                        className="rounded-lg border border-slate-200 px-2 py-1 text-[11px] font-bold text-slate-600">
                        Dismiss
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          <p className="text-[10px] text-slate-400">
            DNA độc lập mỗi kênh — không dùng chéo. Cập nhật: {dna?.updated_at ? new Date(dna.updated_at).toLocaleString() : "—"}
          </p>
        </>
      )}
    </div>
  );
}
