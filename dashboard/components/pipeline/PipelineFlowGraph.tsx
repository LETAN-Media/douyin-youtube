"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { actionGetFlowState } from "@/lib/actions";
import type { FlowRoute, FlowState } from "@/lib/types";
import { formatTime } from "@/lib/format";
import { FlowEdge, hPath, vPath, type FlowEdgeLook } from "./FlowConnector";
import { FlowNode, type FlowNodeTone } from "./FlowNode";
import { ActiveRoutes } from "./ActiveRoutes";
import {
  IconBolt,
  IconClock,
  IconDestinations,
  IconInventory,
  IconSparkles,
} from "@/components/icons";

// ---------- Fixed-geometry canvas (arithmetically laid out, no measuring) ----------

const SRC_W = 236;
const MID_W = 200;
const DST_W = 256;
const GAP_X = 88;
const PAD = 16;
const GAP_Y = 14;
const SRC_H = 92;
const PROC_H = 80;
const DST_H = 100;

const PALETTE = ["fA", "fB", "fC"];

type Sel = { type: "source" | "dest" | "route"; id: string } | null;

interface PlacedEdge {
  id: string;
  d: string;
  kind: "s" | "c" | "d";
  ref: string;
}

function procTone(state: string): FlowNodeTone {
  if (state === "processing" || state === "syncing") return "indigo";
  if (state === "waiting") return "amber";
  if (state === "error") return "red";
  return "slate";
}

function procLabel(state: string): string {
  switch (state) {
    case "processing":
      return "Processing";
    case "syncing":
      return "Syncing";
    case "waiting":
      return "Waiting";
    case "error":
      return "Error";
    default:
      return "Idle";
  }
}

function sourceStatus(s: FlowState["sources"][number]): {
  label: string;
  tone: FlowNodeTone;
  pulse: boolean;
} {
  if (!s.enabled) return { label: "Disabled", tone: "slate", pulse: false };
  const st = s.sync_status;
  if (st === "failed" || st === "auth_required")
    return { label: st === "auth_required" ? "Cần login" : "Sync lỗi", tone: "red", pulse: false };
  if (st === "running" || st === "queued" || st === "syncing")
    return { label: "Đang quét", tone: "amber", pulse: true };
  if (st === "completed") return { label: "Live", tone: "green", pulse: true };
  return { label: "Idle", tone: "slate", pulse: false };
}

export function PipelineFlowGraph({
  pipelineId,
  initial,
}: {
  pipelineId: string;
  initial: FlowState;
}) {
  const [flow, setFlow] = useState<FlowState>(initial);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [lastOk, setLastOk] = useState(() => Date.now());
  const [live, setLive] = useState(true);
  const [sel, setSel] = useState<Sel>(null);
  const [fading, setFading] = useState<{ route: FlowRoute; removedAt: number }[]>([]);
  const prevRoutes = useRef(new Map(initial.active_routes.map((r) => [r.key, r])));
  const fadeTimers = useRef<ReturnType<typeof setTimeout>[]>([]);

  // Realtime poll: graph state only, never revalidates the page.
  useEffect(() => {
    let stop = false;
    const poll = async () => {
      const r = await actionGetFlowState(pipelineId);
      if (stop) return;
      if (r.ok) {
        setFlow(r.flow);
        setLastOk(Date.now());
        setLive(true);
      } else {
        setLive(false);
      }
      setNowMs(Date.now());
    };
    const id = setInterval(poll, 3000);
    return () => {
      stop = true;
      clearInterval(id);
    };
  }, [pipelineId]);

  useEffect(
    () => () => {
      fadeTimers.current.forEach(clearTimeout);
    },
    [],
  );

  // Completed routes keep a fading emerald glow for ~8s after disappearing.
  useEffect(() => {
    const cur = new Map(flow.active_routes.map((r) => [r.key, r]));
    const gone: FlowRoute[] = [];
    prevRoutes.current.forEach((r, k) => {
      if (!cur.has(k) && !r.failed) gone.push(r);
    });
    prevRoutes.current = cur;
    if (gone.length > 0) {
      const at = Date.now();
      // eslint-disable-next-line react-hooks/set-state-in-effect -- queue fade-out entries
      setFading((f) => [...gone.map((route) => ({ route, removedAt: at })), ...f].slice(0, 6));
      const t = setTimeout(() => {
        setFading((f) => f.filter((x) => Date.now() - x.removedAt < 8000));
      }, 8200);
      fadeTimers.current.push(t);
    }
  }, [flow]);

  const routes = flow.active_routes;
  const colorOf = useMemo(() => {
    const m = new Map<string, number>();
    routes
      .filter((r) => !r.failed)
      .forEach((r, i) => m.set(r.key, i % PALETTE.length));
    return m;
  }, [routes]);

  // ---------- Layout ----------
  const layout = useMemo(() => {
    const nS = Math.max(flow.sources.length, 1);
    const nD = Math.max(flow.destinations.length, 1);
    const hS = nS * SRC_H + (nS - 1) * GAP_Y;
    const hP = 4 * PROC_H + 3 * GAP_Y;
    const hD = nD * DST_H + (nD - 1) * GAP_Y;
    const innerH = Math.max(hS, hP, hD);
    const H = innerH + PAD * 2;
    const W = PAD * 2 + SRC_W + GAP_X + MID_W + GAP_X + DST_W;
    const sx = PAD;
    const mx = PAD + SRC_W + GAP_X;
    const dx = PAD + SRC_W + GAP_X + MID_W + GAP_X;
    const topS = PAD + (innerH - hS) / 2;
    const topP = PAD + (innerH - hP) / 2;
    const topD = PAD + (innerH - hD) / 2;
    const procKeys = ["inventory", "ai", "scheduler", "publisher"];
    const procY: Record<string, number> = {};
    procKeys.forEach((k, i) => {
      procY[k] = topP + i * (PROC_H + GAP_Y);
    });
    const edges: PlacedEdge[] = [];
    flow.sources.forEach((s, i) => {
      const y = topS + i * (SRC_H + GAP_Y) + SRC_H / 2;
      edges.push({
        id: `s:${s.id}`,
        kind: "s",
        ref: s.id,
        d: hPath(sx + SRC_W, y, mx, procY.inventory + PROC_H / 2),
      });
    });
    const cx = mx + MID_W / 2;
    const chain: [string, string][] = [
      ["inventory", "ai"],
      ["ai", "scheduler"],
      ["scheduler", "publisher"],
    ];
    chain.forEach(([a, b], i) => {
      edges.push({
        id: `c:${i}`,
        kind: "c",
        ref: `${a}-${b}`,
        d: vPath(cx, procY[a] + PROC_H, cx, procY[b]),
      });
    });
    flow.destinations.forEach((dst, i) => {
      const y = topD + i * (DST_H + GAP_Y) + DST_H / 2;
      edges.push({
        id: `d:${dst.id}`,
        kind: "d",
        ref: dst.id,
        d: hPath(mx + MID_W, procY.publisher + PROC_H / 2, dx, y),
      });
    });
    return { W, H, sx, mx, dx, topS, topD, procY, edges };
  }, [flow]);

  // ---------- Edge states ----------
  const edgeRoutes = useMemo(() => {
    const m = new Map<string, FlowRoute[]>();
    const add = (id: string, r: FlowRoute) => {
      const arr = m.get(id);
      if (arr) arr.push(r);
      else m.set(id, [r]);
    };
    for (const r of routes) {
      add(`s:${r.source_id}`, r);
      add("c:0", r);
      add("c:1", r);
      add("c:2", r);
      add(`d:${r.destination_id}`, r);
    }
    for (const f of fading) {
      add(`s:${f.route.source_id}`, f.route);
      add("c:0", f.route);
      add("c:1", f.route);
      add("c:2", f.route);
      add(`d:${f.route.destination_id}`, f.route);
    }
    return m;
  }, [routes, fading]);

  const fadingKeys = useMemo(() => new Set(fading.map((f) => f.route.key)), [fading]);

  const edgeLook = (id: string): { look: FlowEdgeLook; dimmed: boolean } => {
    const rs = edgeRoutes.get(id) ?? [];
    const liveRs = rs.filter((r) => !fadingKeys.has(r.key));
    const activeRs = liveRs.filter((r) => !r.failed);
    const failedRs = liveRs.filter((r) => r.failed);
    const fadedRs = rs.filter((r) => fadingKeys.has(r.key));

    let inSel = true;
    if (sel?.type === "route") {
      inSel = liveRs.some((r) => r.key === sel.id) || fadedRs.some((r) => r.key === sel.id);
    } else if (sel?.type === "source") {
      if (id.startsWith("s:")) inSel = id === `s:${sel.id}`;
      else if (id.startsWith("d:")) {
        const dst = flow.destinations.find((d) => `d:${d.id}` === id);
        inSel = !!dst?.enabled;
      } else inSel = true;
    } else if (sel?.type === "dest") {
      if (id.startsWith("d:")) inSel = id === `d:${sel.id}`;
      else if (id.startsWith("s:")) {
        const src = flow.sources.find((s) => `s:${s.id}` === id);
        inSel = !!src?.enabled;
      } else inSel = true;
    }

    if (activeRs.length > 0) {
      if (sel?.type === "route" && !activeRs.some((r) => r.key === sel.id))
        return { look: { kind: "idle" }, dimmed: true };
      const idx = colorOf.get(activeRs[0].key) ?? 0;
      return { look: { kind: "active", gradientId: PALETTE[idx] }, dimmed: !inSel };
    }
    if (failedRs.length > 0) return { look: { kind: "failed" }, dimmed: !inSel };
    if (fadedRs.length > 0) return { look: { kind: "faded" }, dimmed: !inSel };
    return { look: { kind: "idle" }, dimmed: sel != null && !inSel };
  };

  const nodeDim = (kind: "s" | "d", id: string): boolean => {
    if (!sel) return false;
    if (sel.type === "route") {
      const r = routes.find((x) => x.key === sel.id);
      if (!r) return true;
      return kind === "s" ? r.source_id !== id : r.destination_id !== id;
    }
    if (sel.type === "source") {
      if (kind === "s") return sel.id !== id;
      return !(flow.destinations.find((d) => d.id === id)?.enabled ?? false);
    }
    // sel dest
    if (kind === "d") return sel.id !== id;
    return !(flow.sources.find((s) => s.id === id)?.enabled ?? false);
  };

  const onEdgeClick = (e: PlacedEdge) => {
    const rs = (edgeRoutes.get(e.id) ?? []).filter((r) => !fadingKeys.has(r.key));
    if (rs.length > 0) {
      const first = rs.find((r) => !r.failed) ?? rs[0];
      setSel((cur) =>
        cur?.type === "route" && cur.id === first.key ? null : { type: "route", id: first.key },
      );
    } else if (e.kind === "s") {
      setSel((cur) => (cur?.type === "source" && cur.id === e.ref ? null : { type: "source", id: e.ref }));
    } else if (e.kind === "d") {
      setSel((cur) => (cur?.type === "dest" && cur.id === e.ref ? null : { type: "dest", id: e.ref }));
    }
  };

  const selectedRouteKey =
    sel?.type === "route" && routes.some((r) => r.key === sel.id) ? sel.id : null;

  const updatedAgo = Math.max(0, Math.floor((nowMs - lastOk) / 1000));
  const s = flow.summary;

  return (
    <div className="space-y-3">
      {/* Compact summary bar */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-2xl border border-slate-200/90 bg-white px-4 py-2.5 text-[13px] shadow-[0_1px_2px_rgba(15,23,42,0.05)] sm:px-5">
        <span className="flex items-center gap-1.5 font-bold text-slate-700">
          <span className="relative flex h-2 w-2">
            <span className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 ${live ? "bg-emerald-400" : "bg-amber-400"}`} />
            <span className={`relative inline-flex h-2 w-2 rounded-full ${live ? "bg-emerald-500" : "bg-amber-500"}`} />
          </span>
          {live ? "LIVE" : "RETRYING"}
        </span>
        <SummaryStat label="Sources" value={s.sources} />
        <SummaryStat label="Inventory" value={s.inventory_total} />
        <SummaryStat label="Queue" value={s.queue} tone={s.queue > 0 ? "amber" : undefined} />
        <SummaryStat label="Publishing" value={s.publishing} tone={s.publishing > 0 ? "indigo" : undefined} />
        <SummaryStat label="Failed" value={s.failed} tone={s.failed > 0 ? "red" : undefined} />
        <span className="tnum ml-auto text-[11px] font-medium text-slate-400">
          cập nhật {updatedAgo}s trước · 3s/poll
        </span>
      </div>

      {/* Graph canvas: horizontal swipe on mobile */}
      <div className="overflow-x-auto rounded-2xl border border-slate-200/90 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.05)]">
        <div className="flex items-center justify-between gap-2 border-b border-slate-100 px-4 py-2.5 sm:px-5">
          <p className="text-[11px] font-extrabold uppercase tracking-[0.12em] text-slate-400">
            Pipeline flow · Sources → Process → Destinations
          </p>
          {sel ? (
            <button
              type="button"
              onClick={() => setSel(null)}
              className="inline-flex min-h-[32px] items-center rounded-lg px-2.5 py-1 text-xs font-bold text-slate-500 transition hover:bg-slate-100 hover:text-slate-800"
            >
              Xóa highlight
            </button>
          ) : (
            <p className="hidden text-[11px] font-medium text-slate-400 sm:block">
              Bấm node / route để trace
            </p>
          )}
        </div>
        <div className="overflow-x-auto">
          <div
            className="relative mx-auto min-w-[920px]"
            style={{ width: layout.W, height: layout.H }}
            onClick={() => setSel(null)}
          >
            <svg
              className="absolute inset-0"
              width={layout.W}
              height={layout.H}
              aria-hidden
            >
              <defs>
                <linearGradient id="fA" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0%" stopColor="#8b5cf6" />
                  <stop offset="55%" stopColor="#3b82f6" />
                  <stop offset="100%" stopColor="#22d3e8" />
                </linearGradient>
                <linearGradient id="fB" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0%" stopColor="#d946ef" />
                  <stop offset="55%" stopColor="#8b5cf6" />
                  <stop offset="100%" stopColor="#3b82f6" />
                </linearGradient>
                <linearGradient id="fC" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0%" stopColor="#3b82f6" />
                  <stop offset="55%" stopColor="#22d3e8" />
                  <stop offset="100%" stopColor="#34d399" />
                </linearGradient>
              </defs>
              {layout.edges.map((e) => {
                const { look, dimmed } = edgeLook(e.id);
                return (
                  <g key={e.id} onClick={(ev) => ev.stopPropagation()}>
                    <FlowEdge
                      d={e.d}
                      look={look}
                      dimmed={dimmed}
                      onClick={() => onEdgeClick(e)}
                      label={edgeLabel(e, edgeRoutes.get(e.id) ?? [])}
                    />
                  </g>
                );
              })}
            </svg>

            {/* Sources column */}
            {flow.sources.length === 0 ? (
              <ColumnPlaceholder
                x={layout.sx}
                y={PAD}
                width={SRC_W}
                text="Chưa có source"
                hint="Thêm ở tab Sources"
              />
            ) : null}
            {flow.sources.map((src, i) => {
              const st = sourceStatus(src);
              return (
                <span key={src.id} onClick={(ev) => ev.stopPropagation()} className="contents">
                  <FlowNode
                    x={layout.sx}
                    y={layout.topS + i * (SRC_H + GAP_Y)}
                    width={SRC_W}
                    height={SRC_H}
                    avatar={
                      <span className="flex h-full w-full items-center justify-center bg-slate-900 text-[13px] font-black tracking-tight text-cyan-300">
                        Dy
                      </span>
                    }
                    title={src.name}
                    subtitle={src.username ?? "Douyin source"}
                    meta={`${src.inventory_count} videos`}
                    statusLabel={st.label}
                    statusTone={st.tone}
                    statusPulse={st.pulse}
                    selected={sel?.type === "source" && sel.id === src.id}
                    dimmed={nodeDim("s", src.id)}
                    onClick={() =>
                      setSel((cur) =>
                        cur?.type === "source" && cur.id === src.id
                          ? null
                          : { type: "source", id: src.id },
                      )
                    }
                  />
                </span>
              );
            })}

            {/* Processor column */}
            {flow.processors.map((p) => (
              <span key={p.key} className="contents">
                <FlowNode
                  x={layout.mx}
                  y={layout.procY[p.key] ?? 0}
                  width={MID_W}
                  height={PROC_H}
                  avatar={<ProcAvatar procKey={p.key} />}
                  title={p.label}
                  subtitle={p.sub}
                  meta={p.detail}
                  statusLabel={procLabel(p.state)}
                  statusTone={procTone(p.state)}
                  statusPulse={p.state === "processing" || p.state === "syncing" || p.state === "waiting"}
                />
              </span>
            ))}

            {/* Destinations column */}
            {flow.destinations.length === 0 ? (
              <ColumnPlaceholder
                x={layout.dx}
                y={PAD}
                width={DST_W}
                text="Chưa có destination"
                hint="Thêm ở tab Destinations"
              />
            ) : null}
            {flow.destinations.map((dst, i) => {
              const lastPubMs = dst.last_published_at
                ? new Date(dst.last_published_at).getTime()
                : NaN;
              const recentOk = !Number.isNaN(lastPubMs) && nowMs - lastPubMs < 90_000;
              return (
                <span key={dst.id} onClick={(ev) => ev.stopPropagation()} className="contents">
                  <FlowNode
                    x={layout.dx}
                    y={layout.topD + i * (DST_H + GAP_Y)}
                    width={DST_W}
                    height={DST_H}
                    avatar={
                      <span
                        className={`flex h-full w-full items-center justify-center text-[15px] font-black text-white ${
                          dst.platform === "youtube"
                            ? "bg-gradient-to-br from-rose-500 to-red-600"
                            : dst.platform === "facebook"
                              ? "bg-gradient-to-br from-sky-500 to-blue-600"
                              : "bg-gradient-to-br from-slate-500 to-slate-700"
                        }`}
                      >
                        {dst.name.slice(0, 1).toUpperCase()}
                      </span>
                    }
                    title={dst.name}
                    subtitle={dst.platform === "youtube" ? "YouTube" : dst.platform === "facebook" ? "Facebook" : dst.platform}
                    meta={`Hôm nay ${dst.today_published}/${dst.daily_upload_limit} · Tiếp ${formatTime(dst.next_upload)}`}
                    statusLabel={
                      !dst.enabled ? "Paused" : dst.connected ? "Connected" : "Chưa kết nối"
                    }
                    statusTone={!dst.enabled ? "amber" : dst.connected ? "green" : "slate"}
                    statusPulse={!!dst.enabled && dst.connected}
                    selected={sel?.type === "dest" && sel.id === dst.id}
                    dimmed={nodeDim("d", dst.id)}
                    badge={
                      recentOk ? (
                        <span className="inline-flex items-center rounded-full bg-emerald-500 px-2 py-0.5 text-[10px] font-bold text-white shadow">
                          Vừa xong ✓
                        </span>
                      ) : undefined
                    }
                    onClick={() =>
                      setSel((cur) =>
                        cur?.type === "dest" && cur.id === dst.id
                          ? null
                          : { type: "dest", id: dst.id },
                      )
                    }
                  />
                </span>
              );
            })}

            {/* Column captions */}
            <Caption x={layout.sx} y={4} width={SRC_W} text="SOURCES" />
            <Caption x={layout.mx} y={4} width={MID_W} text="PIPELINE FLOW" />
            <Caption x={layout.dx} y={4} width={DST_W} text="DESTINATIONS" />
          </div>
        </div>
        <p className="border-t border-slate-100 px-4 py-2 text-[11px] text-slate-400 sm:hidden sm:px-5">
          Vuốt ngang để xem toàn bộ graph →
        </p>
      </div>

      {/* Active routes panel */}
      <ActiveRoutes
        routes={routes}
        fadingCount={fading.length}
        selectedKey={selectedRouteKey}
        onSelect={(key) => setSel(key ? { type: "route", id: key } : null)}
        nowMs={nowMs}
      />
    </div>
  );
}

function SummaryStat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone?: "amber" | "indigo" | "red";
}) {
  const cls =
    tone === "red"
      ? "text-rose-600"
      : tone === "amber"
        ? "text-amber-600"
        : tone === "indigo"
          ? "text-indigo-600"
          : "text-slate-900";
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400">{label}</span>
      <span className={`tnum text-[15px] font-extrabold ${cls}`}>{value}</span>
    </span>
  );
}

function Caption({ x, y, width, text }: { x: number; y: number; width: number; text: string }) {
  return (
    <div
      className="pointer-events-none absolute text-center text-[10px] font-extrabold uppercase tracking-[0.18em] text-slate-300"
      style={{ left: x, top: y, width }}
    >
      {text}
    </div>
  );
}

function ColumnPlaceholder({
  x,
  y,
  width,
  text,
  hint,
}: {
  x: number;
  y: number;
  width: number;
  text: string;
  hint: string;
}) {
  return (
    <div
      className="absolute flex flex-col items-center justify-center gap-1 rounded-2xl border border-dashed border-slate-300 bg-slate-50/60 p-4 text-center"
      style={{ left: x, top: y, width, height: 92 }}
    >
      <p className="text-xs font-bold text-slate-500">{text}</p>
      <p className="text-[11px] text-slate-400">{hint}</p>
    </div>
  );
}

function ProcAvatar({ procKey }: { procKey: string }) {
  const style =
    procKey === "inventory"
      ? "bg-sky-50 text-sky-600"
      : procKey === "ai"
        ? "bg-violet-50 text-violet-600"
        : procKey === "scheduler"
          ? "bg-amber-50 text-amber-600"
          : "bg-emerald-50 text-emerald-600";
  const icon =
    procKey === "inventory" ? (
      <IconInventory size={18} />
    ) : procKey === "ai" ? (
      <IconSparkles size={18} />
    ) : procKey === "scheduler" ? (
      <IconClock size={18} />
    ) : procKey === "publisher" ? (
      <IconBolt size={18} />
    ) : (
      <IconDestinations size={18} />
    );
  return (
    <span className={`flex h-full w-full items-center justify-center ${style}`}>{icon}</span>
  );
}

function edgeLabel(e: { kind: string; ref: string }, rs: FlowRoute[]): string {
  const live = rs.filter((r) => !r.failed);
  if (live.length > 0)
    return `${live.length} route đang chạy: ${live
      .slice(0, 3)
      .map((r) => `${r.source_name} → ${r.destination_name}`)
      .join("; ")}`;
  const failed = rs.filter((r) => r.failed);
  if (failed.length > 0) return `${failed.length} route lỗi — bấm để xem`;
  return e.kind === "s" ? "Source connector" : e.kind === "d" ? "Destination connector" : "Process connector";
}
