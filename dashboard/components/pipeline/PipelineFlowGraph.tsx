"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { actionGetFlowState } from "@/lib/actions";
import type { FlowRoute, FlowState } from "@/lib/types";
import { formatTime } from "@/lib/format";
import { FlowEdge, type FlowEdgeLook } from "./FlowConnector";
import { FlowNode, type FlowNodeTone } from "./FlowNode";
import { ActiveRoutes } from "./ActiveRoutes";
import {
  FLOW_DST_H,
  FLOW_DST_W,
  FLOW_GAP_Y,
  FLOW_MID_W,
  FLOW_MIN_W,
  FLOW_PAD,
  FLOW_PROC_H,
  FLOW_SRC_H,
  FLOW_SRC_W,
  computeFlowLayout,
  litEdgesForRoute,
  procsForEdge,
  stagesForProc,
  type FlowLayoutEdge,
} from "@/lib/flowLayout";
import {
  IconBolt,
  IconClock,
  IconDestinations,
  IconInventory,
  IconPlus,
  IconSparkles,
} from "@/components/icons";

// ---------- Fixed-geometry canvas (arithmetically laid out, no measuring) ----------
// Compact rows so tall graphs (10 sources) stay readable without blank space.
// Geometry + stage mapping live in lib/flowLayout (unit-tested, no JSX).

const PALETTE = ["fA", "fB", "fC"];
const POLL_VISIBLE_MS = 3000;
const POLL_HIDDEN_MS = 15000;
const FADE_MS = 6000;

type Sel =
  | { type: "source" | "dest" | "route" | "proc"; id: string }
  | null;

type PlacedEdge = FlowLayoutEdge;

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
  const scrollRef = useRef<HTMLDivElement>(null);
  const didInitScroll = useRef(false);

  // Realtime poll: graph state only, never revalidates the page.
  // Hidden tab polls slower; visible again polls immediately.
  useEffect(() => {
    let stop = false;
    let id: ReturnType<typeof setInterval>;
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
    const start = (ms: number) => {
      clearInterval(id);
      id = setInterval(poll, ms);
    };
    const onVis = () => {
      if (document.hidden) start(POLL_HIDDEN_MS);
      else {
        start(POLL_VISIBLE_MS);
        void poll();
      }
    };
    document.addEventListener("visibilitychange", onVis);
    start(document.hidden ? POLL_HIDDEN_MS : POLL_VISIBLE_MS);
    return () => {
      stop = true;
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [pipelineId]);

  useEffect(
    () => () => {
      fadeTimers.current.forEach(clearTimeout);
    },
    [],
  );

  // Completed routes keep a fading emerald flash for ~6s after disappearing.
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
        setFading((f) => f.filter((x) => Date.now() - x.removedAt < FADE_MS));
      }, FADE_MS + 200);
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

  // ---------- Layout (pure, tested in lib/flowLayout) ----------
  const layout = useMemo(
    () =>
      computeFlowLayout(
        flow.sources.map((s) => s.id),
        flow.destinations.map((d) => d.id),
      ),
    [flow],
  );

  // Initial auto-scroll: center first active route, else center full graph.
  useEffect(() => {
    if (didInitScroll.current) return;
    const el = scrollRef.current;
    if (!el || el.scrollWidth <= el.clientWidth + 8) {
      didInitScroll.current = true;
      return;
    }
    didInitScroll.current = true;
    const first =
      flow.active_routes.find((r) => !r.failed) ?? flow.active_routes[0];
    let target: number;
    if (first) {
      const si = flow.sources.findIndex((s) => s.id === first.source_id);
      const cx = si >= 0 ? layout.sx + FLOW_SRC_W / 2 : layout.W / 2;
      target = cx - el.clientWidth / 2;
    } else {
      target = (el.scrollWidth - el.clientWidth) / 2;
    }
    el.scrollLeft = Math.max(0, Math.min(target, el.scrollWidth - el.clientWidth));
  }, [layout, flow, pipelineId]);

  // ---------- Route / edge resolution ----------
  const edgeRoutes = useMemo(() => {
    const m = new Map<string, FlowRoute[]>();
    const add = (id: string, r: FlowRoute) => {
      const arr = m.get(id);
      if (arr) arr.push(r);
      else m.set(id, [r]);
    };
    for (const r of routes) {
      for (const e of litEdgesForRoute(r)) add(e, r);
    }
    // Fading completions flash the whole path green.
    for (const f of fading) {
      const r = f.route;
      for (const e of [`s:${r.source_id}`, "c:0", "c:1", "c:2", `d:${r.destination_id}`])
        add(e, r);
    }
    return m;
  }, [routes, fading]);

  const fadingKeys = useMemo(() => new Set(fading.map((f) => f.route.key)), [fading]);

  // A route selection pointing at a vanished route behaves as no selection.
  const effSel: Sel =
    sel?.type === "route" && !routes.some((r) => r.key === sel.id) ? null : sel;

  // Routes visible under current selection (for highlight + node glow).
  const visibleRoutes = useMemo(() => {
    if (!effSel) return routes;
    if (effSel.type === "route") return routes.filter((r) => r.key === effSel.id);
    if (effSel.type === "source") {
      return routes.filter((r) => r.source_id === effSel.id);
    }
    if (effSel.type === "dest") {
      return routes.filter((r) => r.destination_id === effSel.id);
    }
    // proc selection
    const stages = stagesForProc(effSel.id);
    return routes.filter((r) => stages.includes(r.failed ? "failed" : r.stage));
  }, [routes, effSel]);

  // When a source/dest/proc with zero routes is selected, fall back to
  // potential paths so the trace direction stays visible.
  const potential =
    effSel != null && effSel.type !== "route" && visibleRoutes.length === 0;

  const litSet = useMemo(() => {
    const s = new Set<string>();
    for (const r of visibleRoutes) {
      if (fadingKeys.has(r.key)) continue;
      for (const e of litEdgesForRoute(r)) s.add(e);
    }
    return s;
  }, [visibleRoutes, fadingKeys]);

  const glowProcs = useMemo(() => {
    const s = new Set<string>();
    litSet.forEach((e) => procsForEdge(e).forEach((p) => s.add(p)));
    return s;
  }, [litSet]);

  const glowSources = useMemo(
    () => new Set(visibleRoutes.filter((r) => !r.failed).map((r) => r.source_id)),
    [visibleRoutes],
  );
  const glowDests = useMemo(
    () => new Set(visibleRoutes.filter((r) => !r.failed).map((r) => r.destination_id)),
    [visibleRoutes],
  );
  const failedDests = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of visibleRoutes) {
      if (r.failed) m.set(r.destination_id, (m.get(r.destination_id) ?? 0) + 1);
    }
    return m;
  }, [visibleRoutes]);
  const uploadingDests = useMemo(
    () => new Set(visibleRoutes.filter((r) => !r.failed && r.stage === "uploading").map((r) => r.destination_id)),
    [visibleRoutes],
  );

  const edgeLook = (id: string): { look: FlowEdgeLook; dimmed: boolean } => {
    const rs = (edgeRoutes.get(id) ?? []).filter((r) => !fadingKeys.has(r.key));
    const activeRs = rs.filter((r) => !r.failed);
    const failedRs = rs.filter((r) => r.failed);
    const fadedHere =
      activeRs.length === 0 &&
      failedRs.length === 0 &&
      (edgeRoutes.get(id) ?? []).some((r) => fadingKeys.has(r.key));
    const isLit = litSet.has(id);

    if (activeRs.length > 0) {
      if (!isLit) return { look: { kind: "idle" }, dimmed: true };
      // Prefer the color of a route inside the current selection highlight.
      const pick = activeRs.find((r) => visibleRoutes.includes(r)) ?? activeRs[0];
      const idx = colorOf.get(pick.key) ?? 0;
      return { look: { kind: "active", gradientId: PALETTE[idx] }, dimmed: false };
    }
    if (failedRs.length > 0) {
      if (!isLit) return { look: { kind: "idle" }, dimmed: true };
      return { look: { kind: "failed" }, dimmed: false };
    }
    if (fadedHere) return { look: { kind: "faded" }, dimmed: !!effSel };
    // Idle: faint gray while the graph has activity, full gray when all idle.
    if (!effSel) return { look: { kind: "idle" }, dimmed: routes.length > 0 };
    if (potential && potentialEdge(id)) return { look: { kind: "idle" }, dimmed: false };
    return { look: { kind: "idle" }, dimmed: true };
  };

  const potentialEdge = (id: string): boolean => {
    if (!effSel || effSel.type === "route") return false;
    if (effSel.type === "source") {
      if (id === `s:${effSel.id}`) return true;
      if (id.startsWith("c:")) return true;
      if (id.startsWith("d:")) {
        return flow.destinations.some((d) => `d:${d.id}` === id && d.enabled);
      }
      return false;
    }
    if (effSel.type === "dest") {
      if (id === `d:${effSel.id}`) return true;
      if (id.startsWith("c:")) return true;
      if (id.startsWith("s:")) {
        return flow.sources.some((s) => `s:${s.id}` === id && s.enabled);
      }
      return false;
    }
    return id.startsWith("c:");
  };

  const nodeDim = (kind: "s" | "d" | "p", id: string): boolean => {
    if (!effSel) return false;
    if (effSel.type === "route") {
      const r = routes.find((x) => x.key === effSel.id);
      if (!r) return false;
      if (kind === "s") return r.source_id !== id;
      if (kind === "d") return r.destination_id !== id;
      return !litEdgesForRoute(r).some((e) => procsForEdge(e).includes(id));
    }
    if (effSel.type === "source") {
      if (kind === "s") return effSel.id !== id;
      if (kind === "d")
        return visibleRoutes.length > 0
          ? ![...glowDests].includes(id) && ![...failedDests.keys()].includes(id)
          : !(flow.destinations.find((d) => d.id === id)?.enabled ?? false);
      return false;
    }
    if (effSel.type === "dest") {
      if (kind === "d") return effSel.id !== id;
      if (kind === "s")
        return visibleRoutes.length > 0
          ? ![...glowSources].includes(id)
          : !(flow.sources.find((s) => s.id === id)?.enabled ?? false);
      return false;
    }
    // proc selection
    if (kind === "p") return effSel.id !== id && !glowProcs.has(id);
    if (kind === "s") return visibleRoutes.length > 0 && ![...glowSources].includes(id);
    return visibleRoutes.length > 0 && ![...glowDests].includes(id);
  };

  const procSelected = (key: string) => effSel?.type === "proc" && effSel.id === key;

  const onEdgeClick = (e: PlacedEdge) => {
    const rs = (edgeRoutes.get(e.id) ?? []).filter((r) => !fadingKeys.has(r.key));
    if (rs.length > 0) {
      const first = rs.find((r) => !r.failed) ?? rs[0];
      selectRoute(first.key);
    } else if (e.kind === "s") {
      toggleSel({ type: "source", id: e.ref });
    } else if (e.kind === "d") {
      toggleSel({ type: "dest", id: e.ref });
    } else {
      const proc = e.id === "c:0" ? "ai" : e.id === "c:1" ? "scheduler" : "publisher";
      toggleSel({ type: "proc", id: proc });
    }
  };

  const toggleSel = (next: Exclude<Sel, null>) => {
    setSel((cur) => (cur?.type === next.type && cur.id === next.id ? null : next));
  };

  const selectRoute = (key: string | null) => {
    const next: Sel =
      key && !(effSel?.type === "route" && effSel.id === key)
        ? { type: "route", id: key }
        : null;
    setSel(next);
    if (next) {
      requestAnimationFrame(() => {
        document
          .getElementById("flow-route-detail")
          ?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      });
    }
  };

  const selectedRouteKey = effSel?.type === "route" ? effSel.id : null;

  const updatedAgo = Math.max(0, Math.floor((nowMs - lastOk) / 1000));
  const s = flow.summary;

  return (
    <div className="space-y-3">
      {/* Compact summary bar: single scrollable row */}
      <div className="flex items-center gap-x-4 gap-y-1 overflow-x-auto whitespace-nowrap rounded-2xl border border-slate-200/90 bg-white px-4 py-2 text-[13px] shadow-[0_1px_2px_rgba(15,23,42,0.05)] sm:px-5">
        <span className="flex shrink-0 items-center gap-1.5 font-bold text-slate-700">
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
        <span className="tnum ml-auto shrink-0 text-[11px] font-medium text-slate-400">
          cập nhật {updatedAgo}s trước · 3s/poll
        </span>
      </div>

      {/* Graph canvas: horizontal swipe on mobile */}
      <div className="rounded-2xl border border-slate-200/90 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.05)]">
        <div className="flex items-center justify-between gap-2 border-b border-slate-100 px-4 py-2.5 sm:px-5">
          <p className="text-[11px] font-extrabold uppercase tracking-[0.12em] text-slate-400">
            Pipeline flow · Sources → Process → Destinations
          </p>
          {effSel ? (
            <button
              type="button"
              onClick={() => setSel(null)}
              className="inline-flex min-h-[32px] shrink-0 items-center rounded-lg px-2.5 py-1 text-xs font-bold text-slate-500 transition hover:bg-slate-100 hover:text-slate-800"
            >
              Xóa highlight
            </button>
          ) : (
            <p className="hidden shrink-0 text-[11px] font-medium text-slate-400 sm:block">
              Bấm node / route để trace
            </p>
          )}
        </div>
        <div ref={scrollRef} className="overflow-x-auto">
          <div
            className="relative mx-auto"
            style={{ width: layout.W, height: layout.H, minWidth: FLOW_MIN_W }}
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
              <Link
                href={`/pipelines/${pipelineId}?tab=sources`}
                onClick={(ev) => ev.stopPropagation()}
                style={{ left: layout.sx, top: layout.topS, width: FLOW_SRC_W, height: FLOW_SRC_H }}
                className="absolute flex flex-col items-center justify-center gap-1 rounded-2xl border border-dashed border-indigo-300 bg-indigo-50/50 p-3 text-center transition hover:border-indigo-400 hover:bg-indigo-50"
              >
                <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-indigo-600 text-white">
                  <IconPlus size={16} />
                </span>
                <span className="text-[13px] font-extrabold text-indigo-700">+ Add Source</span>
                <span className="text-[11px] font-medium text-indigo-400">Mở tab Sources</span>
              </Link>
            ) : null}
            {flow.sources.map((src, i) => {
              const st = sourceStatus(src);
              const isLive = glowSources.has(src.id) && (effSel == null || visibleRoutes.some((r) => r.source_id === src.id && !r.failed));
              return (
                <span key={src.id} onClick={(ev) => ev.stopPropagation()} className="contents">
                  <FlowNode
                    x={layout.sx}
                    y={layout.topS + i * (FLOW_SRC_H + FLOW_GAP_Y)}
                    width={FLOW_SRC_W}
                    height={FLOW_SRC_H}
                    avatar={
                      <span className="flex h-full w-full items-center justify-center bg-slate-900 text-xs font-black tracking-tight text-cyan-300">
                        Dy
                      </span>
                    }
                    title={src.name}
                    subtitle={src.username ?? "Douyin source"}
                    meta={`${src.inventory_count} videos`}
                    statusLabel={st.label}
                    statusTone={st.tone}
                    statusPulse={st.pulse}
                    selected={effSel?.type === "source" && effSel.id === src.id}
                    active={isLive}
                    dimmed={nodeDim("s", src.id)}
                    badge={
                      isLive ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500 px-2 py-0.5 text-[10px] font-black tracking-wide text-white shadow">
                          <span className="relative flex h-1.5 w-1.5">
                            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-white opacity-70" />
                            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-white" />
                          </span>
                          LIVE
                        </span>
                      ) : undefined
                    }
                    onClick={() => toggleSel({ type: "source", id: src.id })}
                  />
                </span>
              );
            })}

            {/* Processor column */}
            {flow.processors.map((p) => (
              <span key={p.key} onClick={(ev) => ev.stopPropagation()} className="contents">
                <FlowNode
                  x={layout.mx}
                  y={layout.procY[p.key] ?? 0}
                  width={FLOW_MID_W}
                  height={FLOW_PROC_H}
                  avatar={<ProcAvatar procKey={p.key} />}
                  title={p.label}
                  subtitle={p.sub}
                  meta={p.detail}
                  statusLabel={procLabel(p.state)}
                  statusTone={procTone(p.state)}
                  statusPulse={p.state === "processing" || p.state === "syncing" || p.state === "waiting"}
                  selected={procSelected(p.key)}
                  active={glowProcs.has(p.key)}
                  dimmed={nodeDim("p", p.key)}
                  onClick={() => toggleSel({ type: "proc", id: p.key })}
                  label={`${p.label}: ${procLabel(p.state)} — bấm để xem jobs ở bước này`}
                />
              </span>
            ))}

            {/* Destinations column */}
            {flow.destinations.length === 0 ? (
              <Link
                href={`/pipelines/${pipelineId}?tab=destinations`}
                onClick={(ev) => ev.stopPropagation()}
                style={{ left: layout.dx, top: layout.topD, width: FLOW_DST_W, height: FLOW_DST_H }}
                className="absolute flex flex-col items-center justify-center gap-1 rounded-2xl border border-dashed border-indigo-300 bg-indigo-50/50 p-3 text-center transition hover:border-indigo-400 hover:bg-indigo-50"
              >
                <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-indigo-600 text-white">
                  <IconPlus size={16} />
                </span>
                <span className="text-[13px] font-extrabold text-indigo-700">+ Add Destination</span>
                <span className="text-[11px] font-medium text-indigo-400">Mở tab Destinations</span>
              </Link>
            ) : null}
            {flow.destinations.map((dst, i) => {
              const lastPubMs = dst.last_published_at
                ? new Date(dst.last_published_at).getTime()
                : NaN;
              const recentOk = !Number.isNaN(lastPubMs) && nowMs - lastPubMs < 90_000;
              const failN = failedDests.get(dst.id) ?? 0;
              const receiving = uploadingDests.has(dst.id);
              return (
                <span key={dst.id} onClick={(ev) => ev.stopPropagation()} className="contents">
                  <FlowNode
                    x={layout.dx}
                    y={layout.topD + i * (FLOW_DST_H + FLOW_GAP_Y)}
                    width={FLOW_DST_W}
                    height={FLOW_DST_H}
                    avatar={
                      <span
                        className={`flex h-full w-full items-center justify-center text-sm font-black text-white ${
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
                    selected={effSel?.type === "dest" && effSel.id === dst.id}
                    active={receiving || glowDests.has(dst.id)}
                    failed={failN > 0}
                    dimmed={nodeDim("d", dst.id)}
                    badge={
                      receiving ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-indigo-500 px-2 py-0.5 text-[10px] font-black tracking-wide text-white shadow">
                          <span className="relative flex h-1.5 w-1.5">
                            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-white opacity-70" />
                            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-white" />
                          </span>
                          RECEIVING
                        </span>
                      ) : failN > 0 ? (
                        <span className="inline-flex items-center rounded-full bg-rose-500 px-2 py-0.5 text-[10px] font-black tracking-wide text-white shadow">
                          {failN} FAILED
                        </span>
                      ) : recentOk ? (
                        <span className="inline-flex items-center rounded-full bg-emerald-500 px-2 py-0.5 text-[10px] font-bold text-white shadow">
                          Vừa xong ✓
                        </span>
                      ) : undefined
                    }
                    onClick={() => toggleSel({ type: "dest", id: dst.id })}
                  />
                </span>
              );
            })}

            {/* Column captions */}
            <Caption x={layout.sx} y={6} width={FLOW_SRC_W} text="SOURCES" />
            <Caption x={layout.mx} y={6} width={FLOW_MID_W} text="PIPELINE FLOW" />
            <Caption x={layout.dx} y={6} width={FLOW_DST_W} text="DESTINATIONS" />
          </div>
        </div>
        <p className="border-t border-slate-100 px-4 py-2 text-[11px] text-slate-400 sm:hidden sm:px-5">
          Vuốt ngang để xem toàn bộ graph →
        </p>
      </div>

      {/* Active routes panel */}
      <div id="flow-route-detail" className="scroll-mt-32">
        <ActiveRoutes
          routes={routes}
          fadingCount={fading.length}
          selectedKey={selectedRouteKey}
          onSelect={selectRoute}
          nowMs={nowMs}
        />
      </div>
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
    <span className="flex shrink-0 items-baseline gap-1.5">
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
      <IconInventory size={17} />
    ) : procKey === "ai" ? (
      <IconSparkles size={17} />
    ) : procKey === "scheduler" ? (
      <IconClock size={17} />
    ) : procKey === "publisher" ? (
      <IconBolt size={17} />
    ) : (
      <IconDestinations size={17} />
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
