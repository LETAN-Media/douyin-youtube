"use client";

// SVG edge between two nodes.
// idle = gray static. ambient = gray base + slow faint indigo dash drift
// (connected-state shimmer, no glow, no pulse). active = animated gradient +
// glow + moving pulse dot (real runtime work). failed = red.
// completed-fade = emerald, no pulse.

export { hPath, vPath } from "@/lib/flowLayout";

export type FlowEdgeLook =
  | { kind: "idle" }
  | { kind: "active"; gradientId: string }
  | { kind: "ambient" }
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
  const stroke =
    look.kind === "active"
      ? `url(#${look.gradientId})`
      : look.kind === "failed"
        ? "#f43f5e"
        : look.kind === "faded"
          ? "#34d399"
          : "#cbd5e1";
  const width =
    look.kind === "active" ? 3.5 : look.kind === "ambient" ? 2.5 : look.kind === "idle" ? 2 : 3.5;
  const glow =
    look.kind === "active"
      ? { filter: "drop-shadow(0 0 5px rgba(139,92,246,0.65))" }
      : look.kind === "failed"
        ? { filter: "drop-shadow(0 0 5px rgba(244,63,94,0.55))" }
        : undefined;

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
      {/* Ambient: faint slow indigo drift over the gray base. Pure CSS,
          no glow, no pulse dot — visually weaker than active by design. */}
      {look.kind === "ambient" ? (
        <path
          d={d}
          fill="none"
          stroke="#818cf8"
          strokeWidth={width}
          strokeLinecap="round"
          opacity={0.3}
          className="flow-dash-ambient"
        />
      ) : null}
      {look.kind === "active" || look.kind === "failed" ? (
        <circle r={4.5} fill="#ffffff" stroke={stroke} strokeWidth={2.5} style={glow} className="flow-pulse-dot">
          <animateMotion dur={pulseDur} repeatCount="indefinite" path={d} />
        </circle>
      ) : null}
    </g>
  );
}
