"use client";

// SVG edge between two nodes. Idle = gray. Active = animated gradient +
// glow + moving pulse dot. Failed = red. Completed-fade = emerald, no pulse.

export type FlowEdgeLook =
  | { kind: "idle" }
  | { kind: "active"; gradientId: string }
  | { kind: "failed" }
  | { kind: "faded" };

export function hPath(x1: number, y1: number, x2: number, y2: number): string {
  const c = Math.max(30, Math.abs(x2 - x1) / 2);
  return `M ${x1} ${y1} C ${x1 + c} ${y1}, ${x2 - c} ${y2}, ${x2} ${y2}`;
}

export function vPath(x1: number, y1: number, x2: number, y2: number): string {
  const c = Math.max(24, Math.abs(y2 - y1) / 2);
  return `M ${x1} ${y1} C ${x1} ${y1 + c}, ${x2} ${y2 - c}, ${x2} ${y2}`;
}

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
  const width = look.kind === "idle" ? 2 : 3.5;
  const glow =
    look.kind === "active"
      ? { filter: "drop-shadow(0 0 5px rgba(139,92,246,0.65))" }
      : look.kind === "failed"
        ? { filter: "drop-shadow(0 0 5px rgba(244,63,94,0.55))" }
        : undefined;

  return (
    <g
      opacity={dimmed ? 0.22 : 1}
      style={{ transition: "opacity 0.25s ease" }}
      onClick={onClick}
    >
      {/* Wide invisible hit area for touch */}
      {onClick ? (
        <path
          d={d}
          fill="none"
          stroke="transparent"
          strokeWidth={18}
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
      {look.kind === "active" || look.kind === "failed" ? (
        <circle r={4.5} fill="#ffffff" stroke={stroke} strokeWidth={2.5} style={glow}>
          <animateMotion dur={pulseDur} repeatCount="indefinite" path={d} />
        </circle>
      ) : null}
    </g>
  );
}
