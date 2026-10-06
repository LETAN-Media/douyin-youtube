"use client";

/**
 * PipelineOrbitalView — light, tool-native orbital status view.
 *
 * Same props/API as before; restyled to match the dashboard (white cards,
 * slate text, indigo accents). No planet bloom: flat ring nodes, thin
 * orbit rails, subtle motion. Pure presentational Canvas 2D, zero deps.
 * Backend `active_edges` remain the only source of runtime truth.
 *
 * Perf: one rAF loop, pooled particles, precomputed orbit paths,
 * paused when tab hidden / offscreen / prefers-reduced-motion.
 */

import { useEffect, useRef } from "react";

export interface OrbitalNodeDatum {
  key: string;
  title: string;
  subtitle: string;
  status: string;
}

export interface PipelineOrbitalViewProps {
  pipelineName: string;
  nodes: OrbitalNodeDatum[];
  activeEdges?: string[];
  height?: number;
  /** YouTube channel avatar (circular core). Falls back to initial letter. */
  channelAvatarUrl?: string | null;
  channelName?: string | null;
}

const INDIGO = "#4f46e5";
const INDIGO_SOFT = "#c7d2fe";
const RAIL = "#e2e8f0";
const RAIL_MID = "#cbd5e1";
const INK = "#0f172a";
const SUB = "#64748b";

const TILT = -0.3; // gentle isometric lean
const SQUASH = 0.5; // ellipse y/x ratio (roomier than before)
const ORBIT_FRACTIONS = [0.32, 0.44, 0.56];

function statusColor(status: string, hot: boolean): string {
  const s = (status || "").toLowerCase();
  if (hot || s === "running") return INDIGO;
  if (s === "done") return "#059669";
  if (s === "partial" || s === "waiting") return "#d97706";
  if (s === "ready") return "#334155";
  if (s === "error" || s === "failed") return "#e11d48";
  return "#94a3b8"; // idle / not_configured / unknown
}

function statusLabel(status: string): string {
  return (status || "idle").toUpperCase();
}

/** Deterministic pseudo-random from an integer seed (stable across frames). */
function seeded(seed: number): number {
  let x = (seed * 2654435761) >>> 0;
  x ^= x >>> 15;
  x = (x * 2246822519) >>> 0;
  x ^= x >>> 13;
  return (x >>> 0) / 4294967296;
}

interface OrbitGeom {
  rx: number;
  ry: number;
  rot: number;
  cx: number;
  cy: number;
}

function orbitPoint(o: OrbitGeom, angle: number): { x: number; y: number } {
  const ex = o.rx * Math.cos(angle);
  const ey = o.ry * Math.sin(angle);
  const c = Math.cos(o.rot);
  const s = Math.sin(o.rot);
  return { x: o.cx + ex * c - ey * s, y: o.cy + ex * s + ey * c };
}

export function PipelineOrbitalView({
  pipelineName,
  nodes,
  activeEdges = [],
  height = 380,
  channelAvatarUrl = null,
  channelName = null,
}: PipelineOrbitalViewProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  // Keep latest props for the rAF loop without re-subscribing.
  const dataRef = useRef({ pipelineName, nodes, activeEdges, channelAvatarUrl, channelName });
  dataRef.current = { pipelineName, nodes, activeEdges, channelAvatarUrl, channelName };
  // Avatar image cache (per URL). Loads async; the running loop picks it
  // up automatically, static mode redraws on load.
  const avatarRef = useRef<{ url: string | null; img: HTMLImageElement | null; ready: boolean }>({
    url: null,
    img: null,
    ready: false,
  });

  useEffect(() => {
    const canvasEl = canvasRef.current;
    const wrapEl = wrapRef.current;
    if (!canvasEl || !wrapEl) return;
    const canvas: HTMLCanvasElement = canvasEl;
    const wrap: HTMLDivElement = wrapEl;
    const maybeCtx = canvas.getContext("2d");
    if (!maybeCtx) return;
    const ctx: CanvasRenderingContext2D = maybeCtx;

    let raf = 0;
    let running = false;
    let width = 0;
    let dpr = 1;
    let io: IntersectionObserver | null = null;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    function ensureAvatar(onReady?: () => void) {
      const url = dataRef.current.channelAvatarUrl;
      const cache = avatarRef.current;
      if (!url) {
        cache.url = null;
        cache.img = null;
        cache.ready = false;
        return;
      }
      if (cache.url === url) return; // already loading / loaded
      cache.url = url;
      cache.img = null;
      cache.ready = false;
      const img = new Image();
      img.referrerPolicy = "no-referrer";
      img.onload = () => {
        if (avatarRef.current.url === url) {
          avatarRef.current.img = img;
          avatarRef.current.ready = true;
          onReady?.();
        }
      };
      img.onerror = () => {
        if (avatarRef.current.url === url) {
          avatarRef.current.img = null;
          avatarRef.current.ready = false;
        }
      };
      img.src = url;
    }

    function resize() {
      const w = Math.max(280, wrap.clientWidth);
      const small = w < 480;
      dpr = Math.min(window.devicePixelRatio || 1, small ? 1.5 : 2);
      width = w;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(height * dpr);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${height}px`;
    }
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(wrap);

    // Active node indices derived from backend active_edges ("a->b").
    function activeTargets(): number[] {
      const { nodes: ns, activeEdges: edges } = dataRef.current;
      const keys = ns.map((n) => n.key);
      const out: number[] = [];
      for (const e of edges) {
        const parts = String(e).split("->");
        if (parts.length !== 2) continue;
        const idx = keys.indexOf(parts[1].trim());
        if (idx >= 0 && !out.includes(idx)) out.push(idx);
      }
      return out;
    }

    function frame(nowMs: number) {
      if (!running) return;
      raf = requestAnimationFrame(frame);
      draw(nowMs / 1000);
    }

    function start() {
      if (running || reduced) return;
      running = true;
      raf = requestAnimationFrame(frame);
    }
    function stop() {
      running = false;
      cancelAnimationFrame(raf);
    }

    function draw(t: number) {
      const { pipelineName: name, nodes: ns, channelName } = dataRef.current;
      ensureAvatar();
      const W = width;
      const H = height;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);

      const cx = W / 2;
      const cy = H / 2 + 8;
      // Generous margins so labels never clip at the edges.
      const maxRx = Math.min(W / 2 - 104, 270);
      const orbits: OrbitGeom[] = ORBIT_FRACTIONS.map((f) => ({
        rx: Math.max(70, maxRx * (f / 0.56)),
        ry: Math.max(34, maxRx * (f / 0.56) * SQUASH),
        rot: TILT,
        cx,
        cy,
      }));

      const targets = activeTargets();
      const hotSet = new Set(targets);

      // --- backdrop: faint dotted grid, tool-like ---
      ctx.fillStyle = "rgba(100,116,139,0.16)";
      const step = 26;
      const x0 = (cx % step + step) % step;
      const y0 = (cy % step + step) % step;
      for (let gx = x0; gx < W; gx += step) {
        for (let gy = y0; gy < H; gy += step) {
          ctx.fillRect(gx, gy, 1.4, 1.4);
        }
      }

      // --- orbit rails ---
      orbits.forEach((o, oi) => {
        ctx.save();
        ctx.strokeStyle = oi === 1 ? RAIL_MID : RAIL;
        ctx.lineWidth = oi === 1 ? 1.6 : 1.2;
        ctx.beginPath();
        for (let a = 0; a <= Math.PI * 2 + 0.02; a += 0.05) {
          const p = orbitPoint(o, a);
          if (a === 0) ctx.moveTo(p.x, p.y);
          else ctx.lineTo(p.x, p.y);
        }
        ctx.stroke();
        ctx.restore();
      });

      // --- data packets gliding on rails (small indigo dots) ---
      orbits.forEach((o, oi) => {
        for (let k = 0; k < 2; k++) {
          const ang = t * (0.3 + oi * 0.04) + k * Math.PI + oi * 1.3;
          const p = orbitPoint(o, ang);
          ctx.fillStyle = "rgba(79,70,229,0.28)";
          ctx.beginPath();
          ctx.arc(p.x, p.y, 5, 0, Math.PI * 2);
          ctx.fill();
          ctx.fillStyle = "#4f46e5";
          ctx.beginPath();
          ctx.arc(p.x, p.y, 2.2, 0, Math.PI * 2);
          ctx.fill();
          ctx.fillStyle = "#ffffff";
          ctx.beginPath();
          ctx.arc(p.x, p.y, 0.9, 0, Math.PI * 2);
          ctx.fill();
        }
      });

      // --- satellite nodes: evenly spaced angles, one ring each ---
      const shown = ns.slice(0, 6);
      const n = shown.length;
      const nodePos: Array<{ x: number; y: number }> = [];
      shown.forEach((node, i) => {
        const o = orbits[i % 3];
        // Even 60° spacing around the loop (+ slow drift), so neighbours
        // like AI Metadata / YouTube Destination never bunch up.
        const ang = (i / Math.max(n, 1)) * Math.PI * 2 - Math.PI / 2 + t * 0.06;
        const p = orbitPoint(o, ang);
        nodePos.push(p);
        const hot = hotSet.has(i);
        const col = statusColor(node.status, hot);

        if (hot) {
          const pulse = 10 + 2.5 * Math.sin(t * 4);
          ctx.strokeStyle = "rgba(79,70,229,0.45)";
          ctx.lineWidth = 1.6;
          ctx.beginPath();
          ctx.arc(p.x, p.y, pulse, 0, Math.PI * 2);
          ctx.stroke();
        }
        // soft drop shadow, flat disc, status dot
        ctx.fillStyle = "rgba(15,23,42,0.10)";
        ctx.beginPath();
        ctx.arc(p.x + 1, p.y + 2, 8, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = "#ffffff";
        ctx.beginPath();
        ctx.arc(p.x, p.y, 8, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = hot ? INDIGO : "#cbd5e1";
        ctx.lineWidth = hot ? 2.4 : 1.6;
        ctx.beginPath();
        ctx.arc(p.x, p.y, 8, 0, Math.PI * 2);
        ctx.stroke();
        ctx.fillStyle = col;
        ctx.beginPath();
        ctx.arc(p.x, p.y, 3.4, 0, Math.PI * 2);
        ctx.fill();

        // labels pushed radially outward from the core — separation scales
        // with angular distance, so nothing overlaps.
        const dx = p.x - cx;
        const dy = p.y - cy;
        const len = Math.max(1, Math.hypot(dx, dy));
        const ux = dx / len;
        const uy = dy / len;
        const lx = p.x + ux * 20;
        const ly = p.y + uy * 20;
        const align = Math.abs(ux) > 0.45 ? (ux > 0 ? "left" : "right") : "center";
        ctx.textAlign = align as CanvasTextAlign;
        ctx.fillStyle = hot ? INK : "#1e293b";
        ctx.font = "700 11px system-ui, -apple-system, sans-serif";
        ctx.fillText(node.title.slice(0, 24), lx, ly, 170);
        ctx.fillStyle = SUB;
        ctx.font = "500 10px system-ui, -apple-system, sans-serif";
        ctx.fillText(node.subtitle.slice(0, 28), lx, ly + 13, 170);
        ctx.fillStyle = col;
        ctx.font = "700 9px system-ui, -apple-system, sans-serif";
        ctx.fillText(statusLabel(node.status), lx, ly + 25, 170);
      });

      // --- activity ping: thin beam core -> target + soft ring + chip ---
      const PING_PERIOD = 3;
      const cycle = Math.floor(t / PING_PERIOD);
      const phase = (t % PING_PERIOD) / PING_PERIOD; // 0..1
      const pool = targets.length > 0 ? targets : [1, 2].filter((i) => i < shown.length);
      if (pool.length > 0 && nodePos.length > 0) {
        const targetIdx = pool[cycle % pool.length];
        const tp = nodePos[targetIdx];
        if (tp && phase < 0.5) {
          const a = Math.max(0, 1 - phase / 0.5);
          const grad = ctx.createLinearGradient(cx, cy, tp.x, tp.y);
          grad.addColorStop(0, `rgba(79,70,229,${0.04 * a})`);
          grad.addColorStop(1, `rgba(79,70,229,${0.55 * a})`);
          ctx.strokeStyle = grad;
          ctx.lineWidth = 1.6;
          ctx.setLineDash([5, 5]);
          ctx.lineDashOffset = -t * 30;
          ctx.beginPath();
          ctx.moveTo(cx, cy);
          ctx.lineTo(tp.x, tp.y);
          ctx.stroke();
          ctx.setLineDash([]);
          const rr = 9 + phase * 22;
          ctx.strokeStyle = `rgba(79,70,229,${0.5 * a})`;
          ctx.lineWidth = 1.4;
          ctx.beginPath();
          ctx.arc(tp.x, tp.y, rr, 0, Math.PI * 2);
          ctx.stroke();
          // telemetry chip
          const ms = 120 + Math.floor(seeded(cycle * 7 + targetIdx) * 320);
          const label = cycle % 2 === 0 ? `sync ${ms}ms` : `p: 0.9${cycle % 10} drop`;
          ctx.font = "700 9px ui-monospace, monospace";
          const tw = ctx.measureText(label).width + 12;
          const bx = Math.min(Math.max(tp.x + 14, 4), W - tw - 4);
          const by = Math.max(tp.y - 32, 4);
          ctx.fillStyle = `rgba(255,255,255,${0.92 * a + 0.05})`;
          ctx.strokeStyle = `rgba(79,70,229,${0.6 * a})`;
          ctx.lineWidth = 1;
          if (typeof ctx.roundRect === "function") {
            ctx.beginPath();
            ctx.roundRect(bx, by, tw, 16, 8);
            ctx.fill();
            ctx.stroke();
          } else {
            ctx.fillRect(bx, by, tw, 16);
          }
          ctx.fillStyle = `rgba(67,56,202,${Math.min(1, a + 0.3)})`;
          ctx.textAlign = "left";
          ctx.fillText(label, bx + 6, by + 11.5);
        }
      }

      // --- core hub: circular channel avatar (fallback: initial) ---
      const AVATAR_R = 22;
      const avatar = avatarRef.current;
      ctx.save();
      ctx.beginPath();
      ctx.arc(cx, cy, AVATAR_R, 0, Math.PI * 2);
      ctx.clip();
      if (avatar.ready && avatar.img) {
        // cover-fit the square-ish avatar into the circle
        const iw = avatar.img.naturalWidth || AVATAR_R * 2;
        const ih = avatar.img.naturalHeight || AVATAR_R * 2;
        const s = Math.max((AVATAR_R * 2) / iw, (AVATAR_R * 2) / ih);
        const dw = iw * s;
        const dh = ih * s;
        ctx.drawImage(avatar.img, cx - dw / 2, cy - dh / 2, dw, dh);
      } else {
        ctx.fillStyle = "#eef1ff";
        ctx.fillRect(cx - AVATAR_R, cy - AVATAR_R, AVATAR_R * 2, AVATAR_R * 2);
        const initial = ((channelName || name || "?").trim().charAt(0) || "?").toUpperCase();
        ctx.fillStyle = INDIGO;
        ctx.font = "800 20px system-ui, -apple-system, sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(initial, cx, cy + 1);
        ctx.textBaseline = "alphabetic";
      }
      ctx.restore();
      ctx.strokeStyle = "#e0e7ff";
      ctx.lineWidth = 2.5;
      ctx.beginPath();
      ctx.arc(cx, cy, AVATAR_R, 0, Math.PI * 2);
      ctx.stroke();

      const short = name.length > 22 ? name.slice(0, 21) + "…" : name;
      ctx.textAlign = "center";
      ctx.fillStyle = INK;
      ctx.font = "800 13px system-ui, -apple-system, sans-serif";
      ctx.fillText(short.toUpperCase(), cx, cy + 48, W - 40);
      ctx.fillStyle = INDIGO;
      ctx.font = "700 9px system-ui, -apple-system, sans-serif";
      ctx.fillText("CORE PIPELINE", cx, cy + 61, W - 40);
      const seq = String(Math.floor(t / 0.8) % 30 + 1).padStart(3, "0");
      ctx.fillStyle = SUB;
      ctx.font = "700 9px ui-monospace, monospace";
      ctx.fillText(`#${seq}`, cx, cy + 73, W - 40);
    }

    function drawStatic() {
      draw(1.2);
    }

    if (reduced) {
      resize();
      ensureAvatar(() => drawStatic());
      drawStatic();
    } else {
      ensureAvatar();
      io = new IntersectionObserver(
        (entries) => {
          if (entries[0]?.isIntersecting && !document.hidden) start();
          else stop();
        },
        { threshold: 0.05 },
      );
      io.observe(wrap);
      const onVis = () => {
        if (document.hidden) stop();
        else start();
      };
      document.addEventListener("visibilitychange", onVis);
      // initial kick in case already visible
      start();
      var cleanupVis = () => document.removeEventListener("visibilitychange", onVis);
    }

    return () => {
      stop();
      ro.disconnect();
      io?.disconnect();
      if (typeof cleanupVis !== "undefined") cleanupVis();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [height]);

  return (
    <div
      ref={wrapRef}
      className="relative w-full overflow-hidden rounded-3xl border border-slate-200/90 bg-gradient-to-b from-white to-indigo-50/40 shadow-[0_1px_2px_rgba(15,23,42,0.05)]"
    >
      <canvas ref={canvasRef} className="block w-full" aria-label={`Pipeline orbit: ${pipelineName}`} />
      <div className="pointer-events-none absolute left-3 top-2.5 flex items-center gap-1.5">
        <span className="relative flex h-1.5 w-1.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-indigo-500 opacity-60" />
          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-indigo-600" />
        </span>
        <span className="text-[10px] font-bold uppercase tracking-[0.2em] text-indigo-500">
          Pipeline live
        </span>
      </div>
    </div>
  );
}
