"use client";

// SVG edge between two nodes.
// idle = gray static. ambient = gradient base + drifting highlight dash +
// soft glowing dot travelling along the path (connected-state shimmer,
// slower and softer than active by design). active = animated gradient +
// strong glow + fast pulse dot (real runtime work). failed = red.
// completed-fade = emerald, no pulse.

export { hPath, vPath } from "@/lib/flowLayout";

export type FlowEdgeLook =
  | { kind: "idle" }
  | { kind: "active"; gradientId: string }
  | { kind: "ambient"; gradientId: string; phase?: string }
  | { kind: "failed" }
  | { kind: "faded" };

export function FlowEdge({
  d,
  look,
  dimmed = false,
  pulseDur = "1.5s",
  onClick,
  label,
}: {
  d: string;
  look: FlowEdgeLook;
  dimmed?: boolean;
  pulseDur?: string;
  onClick?: () => void;
  label?: string;
}) {
  const isAmbient = look.kind === "ambient";
  const stroke =
    look.kind === "active"
      ? `url(#${look.gradientId})`
      : isAmbient
        ? `url(#${look.gradientId})`
        : look.kind === "failed"
          ? "#f43f5e"
          : look.kind === "faded"
            ? "#34d399"
            : "#cbd5e1";
  const width =
    look.kind === "active" ? 3.5 : isAmbient ? 3 : look.kind === "idle" ? 2 : 3.5;
  const glow =
    look.kind === "active"
      ? { filter: "drop-shadow(0 0 5px rgba(139,92,246,0.65))" }
      : look.kind === "failed"
        ? { filter: "drop-shadow(0 0 5px rgba(244,63,94,0.55))" }
        : undefined;
  const softGlow = { filter: "drop-shadow(0 0 4px rgba(99,102,241,0.55))" };

  return (
    <g
      opacity={dimmed ? 0.3 : 1}
      style={{ transition: "opacity 0.25s ease" }}
      onClick={onClick}
    >
      {/* Wide invisible hit area for touch */}
      {onClick ? (
        <path
          d={d}
          fill="none"
          stroke="transparent"
          strokeWidth={22}
          style={{ cursor: "pointer", pointerEvents: "stroke" }}
        >
          {label ? <title>{label}</title> : null}
        </path>
      ) : null}
      <path
        d={d}
        fill="none"
        stroke={stroke}
        strokeWidth={width}
        strokeLinecap="round"
        style={glow}
        className={look.kind === "active" ? "flow-dash" : undefined}
      />
      {/* Ambient: gradient base + drifting highlight + travelling glow dot.
          Brighter than the old faint version, but still slower, thinner and
          softer than active — no mistaking connected vs processing. */}
      {isAmbient ? (
        <>
          <path
            d={d}
            fill="none"
            stroke="#6366f1"
            strokeWidth={width}
            strokeLinecap="round"
            opacity={0.5}
            className="flow-dash-ambient"
          />
          <circle
            r={3.5}
            fill="#eef2ff"
            stroke="#6366f1"
            strokeWidth={2}
            style={softGlow}
            className="flow-pulse-dot"
          >
            <animateMotion
              dur="3s"
              begin={look.phase ?? "0s"}
              repeatCount="indefinite"
              path={d}
            />
          </circle>
        </>
      ) : null}
      {look.kind === "active" || look.kind === "failed" ? (
        <circle r={4.5} fill="#ffffff" stroke={stroke} strokeWidth={2.5} style={glow} className="flow-pulse-dot">
          <animateMotion dur={pulseDur} repeatCount="indefinite" path={d} />
        </circle>
      ) : null}
    </g>
  );
}
