// Pure flow-graph geometry + stage mapping (no JSX).
// Unit-testable with plain node: no runtime imports.

import type { FlowRoute } from "./types";

// ---------- Canvas constants ----------

export const FLOW_SRC_W = 236;
export const FLOW_MID_W = 200;
export const FLOW_DST_W = 256;
export const FLOW_GAP_X = 88;
export const FLOW_PAD = 32; // min canvas margin: 32px mobile, more centered desktop
export const FLOW_GAP_Y = 12;
export const FLOW_SRC_H = 78;
export const FLOW_PROC_H = 74;
export const FLOW_DST_H = 84;
export const FLOW_MIN_W = 940;

export const FLOW_PROC_KEYS = ["inventory", "ai", "scheduler", "publisher"] as const;

// ---------- Edge path builders ----------

export function hPath(x1: number, y1: number, x2: number, y2: number): string {
  const c = Math.max(30, Math.abs(x2 - x1) / 2);
  return `M ${x1} ${y1} C ${x1 + c} ${y1}, ${x2 - c} ${y2}, ${x2} ${y2}`;
}

export function vPath(x1: number, y1: number, x2: number, y2: number): string {
  const c = Math.max(24, Math.abs(y2 - y1) / 2);
  return `M ${x1} ${y1} C ${x1} ${y1 + c}, ${x2} ${y2 - c}, ${x2} ${y2}`;
}

// ---------- Stage -> lit edges (partial-path highlight) ----------

export function litEdgesForRoute(r: Pick<FlowRoute, "source_id" | "destination_id" | "stage" | "failed">): string[] {
  const s = `s:${r.source_id}`;
  const d = `d:${r.destination_id}`;
  if (r.failed) return [s, "c:0", "c:1", "c:2", d];
  switch (r.stage) {
    case "uploading":
    case "published":
      return [s, "c:0", "c:1", "c:2", d];
    case "scheduled":
      return [s, "c:0", "c:1"];
    case "ai_metadata":
      return [s, "c:0"];
    case "queued":
      return []; // waiting: source node glows, no edges yet
    case "pending":
    case "downloading":
    default:
      return [s];
  }
}

// ---------- Edge -> processor keys (node glow) ----------

export function procsForEdge(edgeId: string): string[] {
  if (edgeId.startsWith("s:")) return ["inventory"];
  if (edgeId === "c:0") return ["inventory", "ai"];
  if (edgeId === "c:1") return ["ai", "scheduler"];
  if (edgeId === "c:2") return ["scheduler", "publisher"];
  if (edgeId.startsWith("d:")) return ["publisher"];
  return [];
}

// ---------- Processor -> stages (click processor highlights these jobs) ----------

export function stagesForProc(procKey: string): string[] {
  switch (procKey) {
    case "inventory":
      return ["pending", "downloading"];
    case "ai":
      return ["ai_metadata"];
    case "scheduler":
      return ["queued", "scheduled"];
    case "publisher":
    default:
      return ["uploading", "published", "failed"];
  }
}

// ---------- Layout ----------

export interface FlowLayoutEdge {
  id: string;
  d: string;
  kind: "s" | "c" | "d";
  ref: string;
}

export interface FlowLayout {
  W: number;
  H: number;
  sx: number;
  mx: number;
  dx: number;
  topS: number;
  topD: number;
  procY: Record<string, number>;
  edges: FlowLayoutEdge[];
}

export function computeFlowLayout(
  sourceIds: string[],
  destIds: string[],
): FlowLayout {
  const nS = Math.max(sourceIds.length, 1);
  const nD = Math.max(destIds.length, 1);
  const hS = nS * FLOW_SRC_H + (nS - 1) * FLOW_GAP_Y;
  const hP = FLOW_PROC_KEYS.length * FLOW_PROC_H + (FLOW_PROC_KEYS.length - 1) * FLOW_GAP_Y;
  const hD = nD * FLOW_DST_H + (nD - 1) * FLOW_GAP_Y;
  const innerH = Math.max(hS, hP, hD);
  const H = innerH + FLOW_PAD * 2;
  const W = FLOW_PAD * 2 + FLOW_SRC_W + FLOW_GAP_X + FLOW_MID_W + FLOW_GAP_X + FLOW_DST_W;
  const sx = FLOW_PAD;
  const mx = FLOW_PAD + FLOW_SRC_W + FLOW_GAP_X;
  const dx = FLOW_PAD + FLOW_SRC_W + FLOW_GAP_X + FLOW_MID_W + FLOW_GAP_X;
  const topS = FLOW_PAD + (innerH - hS) / 2;
  const topP = FLOW_PAD + (innerH - hP) / 2;
  const topD = FLOW_PAD + (innerH - hD) / 2;
  const procY: Record<string, number> = {};
  FLOW_PROC_KEYS.forEach((k, i) => {
    procY[k] = topP + i * (FLOW_PROC_H + FLOW_GAP_Y);
  });
  const edges: FlowLayoutEdge[] = [];
  sourceIds.forEach((id, i) => {
    const y = topS + i * (FLOW_SRC_H + FLOW_GAP_Y) + FLOW_SRC_H / 2;
    edges.push({
      id: `s:${id}`,
      kind: "s",
      ref: id,
      d: hPath(sx + FLOW_SRC_W, y, mx, procY.inventory + FLOW_PROC_H / 2),
    });
  });
  const cx = mx + FLOW_MID_W / 2;
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
      d: vPath(cx, procY[a] + FLOW_PROC_H, cx, procY[b]),
    });
  });
  destIds.forEach((id, i) => {
    const y = topD + i * (FLOW_DST_H + FLOW_GAP_Y) + FLOW_DST_H / 2;
    edges.push({
      id: `d:${id}`,
      kind: "d",
      ref: id,
      d: hPath(mx + FLOW_MID_W, procY.publisher + FLOW_PROC_H / 2, dx, y),
    });
  });
  return { W, H, sx, mx, dx, topS, topD, procY, edges };
}
