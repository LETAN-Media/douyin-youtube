"use client";

/**
 * PipelineOrbitalView — cyberpunk orbital telemetry visualization.
 *
 * Pure presentational Canvas 2D (no WebGL/three.js dependency by design:
 * a single 2D layer at capped DPR holds 60fps on mobile). All pipeline
 * data arrives via props; this component never fetches and never mutates
 * flow logic. Backend `active_edges` remain the only source of runtime
 * truth — here they only pick laser targets and hot nodes.
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
}

const PINK = "#ff2a70";
const PINK_HOT = "#ff5c9d";
const VIOLET = "#a78bfa";
const ICE = "#e8ecff";

const TILT = -0.32; // isometric lean (radians)
const SQUASH = 0.42; // ellipse y/x ratio
const ORBIT_FRACTIONS = [0.3, 0.4, 0.485]; // of half-width

function statusColor(status: string, hot: boolean): string {
  const s = (status || "").toLowerCase();
  if (hot || s === "running") return PINK_HOT;
  if (s === "done") return VIOLET;
  if (s === "ready" || s === "partial" || s === "waiting") return "#c3c9e8";
  if (s === "error" || s === "failed") return "#fb7185";
  return "#5b6076"; // idle / not_configured / unknown
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
  height = 360,
}: PipelineOrbitalViewProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  // Keep latest props for the rAF loop without re-subscribing.
  const dataRef = useRef({ pipelineName, nodes, activeEdges });
  dataRef.current = { pipelineName, nodes, activeEdges };

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
      const { pipelineName: name, nodes: ns } = dataRef.current;
      const W = width;
      const H = height;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);

      const cx = W / 2;
      const cy = H / 2 + 6;
      const maxRx = Math.min(W / 2 - 66, 250);
      const orbits: OrbitGeom[] = ORBIT_FRACTIONS.map((f) => ({
        rx: Math.max(60, maxRx * (f / 0.485)),
        ry: Math.max(26, maxRx * (f / 0.485) * SQUASH),
        rot: TILT,
        cx,
        cy,
      }));

      const targets = activeTargets();
      const hotSet = new Set(targets);

      // --- backdrop: vignette + grid dots (cheap, static-ish) ---
      const bg = ctx.createRadialGradient(cx, cy, 10, cx, cy, Math.max(W, H) * 0.7);
      bg.addColorStop(0, "rgba(255,42,112,0.07)");
      bg.addColorStop(0.55, "rgba(20,16,40,0.25)");
      bg.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = bg;
      ctx.fillRect(0, 0, W, H);

      // --- starfield dust: fixed seeds, twinkle by time ---
      for (let i = 0; i < 42; i++) {
        const sx = seeded(i * 2 + 1) * W;
        const sy = seeded(i * 2 + 2) * H;
        const tw = 0.25 + 0.55 * (0.5 + 0.5 * Math.sin(t * (0.6 + seeded(i) * 1.4) + i));
        ctx.globalAlpha = tw * 0.5;
        ctx.fillStyle = i % 5 === 0 ? PINK : "#aab2d8";
        const r = i % 7 === 0 ? 1.6 : 1;
        ctx.beginPath();
        ctx.arc(sx, sy, r, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;

      // --- orbits ---
      orbits.forEach((o, oi) => {
        ctx.save();
        ctx.strokeStyle = oi === 1 ? "rgba(167,139,250,0.4)" : "rgba(139,144,168,0.28)";
        ctx.lineWidth = oi === 1 ? 1.4 : 1;
        ctx.beginPath();
        for (let a = 0; a <= Math.PI * 2 + 0.02; a += 0.05) {
          const p = orbitPoint(o, a);
          if (a === 0) ctx.moveTo(p.x, p.y);
          else ctx.lineTo(p.x, p.y);
        }
        ctx.stroke();
        ctx.restore();
      });

      // --- data packets gliding on orbits ---
      orbits.forEach((o, oi) => {
        for (let k = 0; k < 2; k++) {
          const ang = t * (0.32 + oi * 0.05) + k * Math.PI + oi * 1.3;
          const p = orbitPoint(o, ang);
          const g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, 7);
          g.addColorStop(0, "rgba(255,255,255,0.95)");
          g.addColorStop(0.35, "rgba(255,42,112,0.75)");
          g.addColorStop(1, "rgba(255,42,112,0)");
          ctx.fillStyle = g;
          ctx.beginPath();
          ctx.arc(p.x, p.y, 7, 0, Math.PI * 2);
          ctx.fill();
          ctx.fillStyle = "#fff";
          ctx.beginPath();
          ctx.arc(p.x, p.y, 1.6, 0, Math.PI * 2);
          ctx.fill();
        }
      });

      // --- satellite nodes (slow drift, alternating orbits) ---
      const shown = ns.slice(0, 6);
      const nodePos: Array<{ x: number; y: number }> = [];
      shown.forEach((n, i) => {
        const o = orbits[i % 3];
        const spread = (Math.PI * 2) / Math.max(2, Math.ceil(shown.length / 3));
        const ang = t * 0.07 * (i % 3 === 1 ? -1 : 1) + i * 1.05 + spread * Math.floor(i / 3);
        const p = orbitPoint(o, ang);
        nodePos.push(p);
        const hot = hotSet.has(i);
        const col = statusColor(n.status, hot);

        if (hot) {
          const pulse = 6 + 3 * Math.sin(t * 4);
          const hg = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, 16 + pulse);
          hg.addColorStop(0, "rgba(255,42,112,0.5)");
          hg.addColorStop(1, "rgba(255,42,112,0)");
          ctx.fillStyle = hg;
          ctx.beginPath();
          ctx.arc(p.x, p.y, 16 + pulse, 0, Math.PI * 2);
          ctx.fill();
        }
        // node ring + core dot
        ctx.strokeStyle = col;
        ctx.globalAlpha = hot ? 1 : 0.85;
        ctx.lineWidth = hot ? 2 : 1.4;
        ctx.beginPath();
        ctx.arc(p.x, p.y, hot ? 6 : 5, 0, Math.PI * 2);
        ctx.stroke();
        ctx.globalAlpha = 1;
        ctx.fillStyle = hot ? "#fff" : col;
        ctx.beginPath();
        ctx.arc(p.x, p.y, hot ? 2.6 : 2, 0, Math.PI * 2);
        ctx.fill();

        // labels (alternate above/below to avoid collisions)
        const above = i % 2 === 0;
        const ly = p.y + (above ? -14 : 14);
        ctx.textAlign = "center";
        ctx.fillStyle = hot ? "#ffffff" : ICE;
        ctx.font = "700 11px system-ui, -apple-system, sans-serif";
        ctx.fillText(n.title.slice(0, 22), p.x, above ? ly - 12 : ly + 4, 150);
        ctx.fillStyle = "rgba(200,205,230,0.75)";
        ctx.font = "500 10px system-ui, -apple-system, sans-serif";
        ctx.fillText(n.subtitle.slice(0, 26), p.x, above ? ly : ly + 16, 150);
        ctx.fillStyle = col;
        ctx.font = "700 9px system-ui, -apple-system, sans-serif";
        ctx.fillText(statusLabel(n.status), p.x, above ? ly + 12 : ly + 28, 150);
      });

      // --- laser ping: core -> alternating hot (or fallback) target ---
      const PING_PERIOD = 2.8;
      const cycle = Math.floor(t / PING_PERIOD);
      const phase = (t % PING_PERIOD) / PING_PERIOD; // 0..1
      const pool = targets.length > 0 ? targets : [1, 2].filter((i) => i < shown.length);
      if (pool.length > 0 && nodePos.length > 0) {
        const targetIdx = pool[cycle % pool.length];
        const tp = nodePos[targetIdx];
        if (tp && phase < 0.55) {
          const a = Math.max(0, 1 - phase / 0.55);
          const grad = ctx.createLinearGradient(cx, cy, tp.x, tp.y);
          grad.addColorStop(0, `rgba(255,42,112,${0.05 * a})`);
          grad.addColorStop(1, `rgba(255,92,157,${0.9 * a})`);
          ctx.strokeStyle = grad;
          ctx.lineWidth = 1.8;
          ctx.setLineDash([6, 5]);
          ctx.lineDashOffset = -t * 40;
          ctx.beginPath();
          ctx.moveTo(cx, cy);
          ctx.lineTo(tp.x, tp.y);
          ctx.stroke();
          ctx.setLineDash([]);
          // impact ring
          const rr = 4 + phase * 26;
          ctx.strokeStyle = `rgba(255,92,157,${0.7 * a})`;
          ctx.lineWidth = 1.5;
          ctx.beginPath();
          ctx.arc(tp.x, tp.y, rr, 0, Math.PI * 2);
          ctx.stroke();
          // telemetry badge
          const ms = 120 + Math.floor(seeded(cycle * 7 + targetIdx) * 320);
          const label = cycle % 2 === 0 ? `sync ${ms}ms` : `p: 0.9${cycle % 10} drop`;
          ctx.font = "700 9px ui-monospace, monospace";
          const tw = ctx.measureText(label).width + 12;
          const bx = Math.min(Math.max(tp.x + 12, 4), W - tw - 4);
          const by = Math.max(tp.y - 30, 4);
          ctx.fillStyle = `rgba(8,8,12,${0.85 * a + 0.1})`;
          ctx.strokeStyle = `rgba(255,42,112,${0.8 * a})`;
          ctx.lineWidth = 1;
          if (typeof ctx.roundRect === "function") {
            ctx.beginPath();
            ctx.roundRect(bx, by, tw, 16, 4);
            ctx.fill();
            ctx.stroke();
          } else {
            ctx.fillRect(bx, by, tw, 16);
          }
          ctx.fillStyle = `rgba(255,255,255,${Math.min(1, a + 0.25)})`;
          ctx.textAlign = "left";
          ctx.fillText(label, bx + 6, by + 11.5);
        }
      }

      // --- core hub ---
      const breathe = 1 + 0.06 * Math.sin(t * 2.2);
      // signal rings
      for (let k = 0; k < 2; k++) {
        const rr = (20 + ((t * 22 + k * 22) % 44)) * breathe;
        const alpha = Math.max(0, 0.5 - ((t * 22 + k * 22) % 44) / 44 * 0.5);
        ctx.strokeStyle = `rgba(255,42,112,${alpha.toFixed(3)})`;
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.arc(cx, cy, rr, 0, Math.PI * 2);
        ctx.stroke();
      }
      const coreG = ctx.createRadialGradient(cx, cy, 0, cx, cy, 26 * breathe);
      coreG.addColorStop(0, "#ffffff");
      coreG.addColorStop(0.35, "#ff5c9d");
      coreG.addColorStop(0.7, "#ff2a70");
      coreG.addColorStop(1, "rgba(255,42,112,0)");
      ctx.fillStyle = coreG;
      ctx.beginPath();
      ctx.arc(cx, cy, 26 * breathe, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#0b0b10";
      ctx.beginPath();
      ctx.arc(cx, cy, 9, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = PINK_HOT;
      ctx.beginPath();
      ctx.arc(cx, cy, 3.4 + Math.sin(t * 5) * 0.8, 0, Math.PI * 2);
      ctx.fill();

      // core labels
      const short = name.length > 20 ? name.slice(0, 19) + "…" : name;
      ctx.textAlign = "center";
      ctx.fillStyle = "#ffffff";
      ctx.font = "800 13px system-ui, -apple-system, sans-serif";
      ctx.fillText(short.toUpperCase(), cx, cy + 44, W - 40);
      ctx.fillStyle = "rgba(255,92,157,0.9)";
      ctx.font = "700 9px system-ui, -apple-system, sans-serif";
      ctx.fillText("CORE PIPELINE", cx, cy + 57, W - 40);
      const seq = String(Math.floor(t / 0.8) % 30 + 1).padStart(3, "0");
      ctx.fillStyle = "rgba(200,205,230,0.8)";
      ctx.font = "700 9px ui-monospace, monospace";
      ctx.fillText(`#${seq}`, cx, cy + 69, W - 40);
    }

    function drawStatic() {
      draw(1.2);
    }

    if (reduced) {
      resize();
      drawStatic();
    } else {
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
      className="relative w-full overflow-hidden rounded-3xl border border-[#1d1526] bg-[#08080c] shadow-[0_0_40px_rgba(255,42,112,0.08)]"
    >
      <canvas ref={canvasRef} className="block w-full" aria-label={`Pipeline orbit: ${pipelineName}`} />
      <div className="pointer-events-none absolute left-3 top-2.5 flex items-center gap-1.5">
        <span className="relative flex h-1.5 w-1.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#ff2a70] opacity-60" />
          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-[#ff2a70]" />
        </span>
        <span className="text-[10px] font-bold uppercase tracking-[0.2em] text-[#ff5c9d]">
          Orbital telemetry
        </span>
      </div>
    </div>
  );
}
