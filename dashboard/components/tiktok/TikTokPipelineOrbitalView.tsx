"use client";

import { useEffect, useRef, useState } from "react";
import type { TikTokFlowBackendStatus } from "@/lib/tiktok-api";

export interface TikTokOrbitalNodeDatum {
  key: string;
  title: string;
  subtitle: string;
  status: TikTokFlowBackendStatus;
}

export interface TikTokPipelineOrbitalViewProps {
  pipelineName: string;
  autoPublish?: boolean;
  live?: boolean;
  nodes: TikTokOrbitalNodeDatum[];
  activeEdges?: string[];
  channelAvatarUrl?: string | null;
  channelName?: string | null;
}

// 6 node positions around ellipse: cx=360, cy=190, rx=250, ry=115
// Angle order is clockwise starting at top (-90 deg):
// 0: Source (-90 deg) -> (360, 75)
// 1: Inventory (-30 deg) -> (577, 133)
// 2: AI Metadata (30 deg) -> (577, 248)
// 3: Scheduler (90 deg) -> (360, 305)
// 4: Publisher (150 deg) -> (143, 248)
// 5: YouTube Destination (210 deg) -> (143, 133)
const NODE_COORDINATES = [
  { x: 360, y: 75, align: "center" as const },
  { x: 575, y: 133, align: "right" as const },
  { x: 575, y: 247, align: "right" as const },
  { x: 360, y: 305, align: "center" as const },
  { x: 145, y: 247, align: "left" as const },
  { x: 145, y: 133, align: "left" as const },
];

function getStatusTheme(status: string) {
  switch (status) {
    case "ready":
      return { bg: "#ecfdf5", border: "#a7f3d0", text: "#047857", dot: "#10b981", badge: "READY" };
    case "running":
      return { bg: "#e0e7ff", border: "#818cf8", text: "#4338ca", dot: "#6366f1", badge: "RUNNING" };
    case "waiting":
      return { bg: "#fef3c7", border: "#fde68a", text: "#b45309", dot: "#f59e0b", badge: "WAITING" };
    case "done":
      return { bg: "#ecfdf5", border: "#a7f3d0", text: "#047857", dot: "#10b981", badge: "DONE" };
    case "error":
      return { bg: "#ffe4e6", border: "#fecdd3", text: "#be123c", dot: "#f43f5e", badge: "ERROR" };
    case "partial":
      return { bg: "#f5f3ff", border: "#ddd6fe", text: "#6d28d9", dot: "#8b5cf6", badge: "PARTIAL" };
    default:
      return { bg: "#f8fafc", border: "#e2e8f0", text: "#64748b", dot: "#94a3b8", badge: "IDLE" };
  }
}

function NodeIcon({ nodeKey, color }: { nodeKey: string; color: string }) {
  if (nodeKey === "source") {
    // TikTok note
    return (
      <path
        d="M -3 3 C -3 4.5 -1.5 5.5 0 5.5 C 1.8 5.5 3 4.3 3 2.5 L 3 -5 C 4 -4 5.5 -3.5 7 -3.5 L 7 -6 C 5.5 -6 4 -7 3.5 -8 L 1 -8 L 1 1 C 0.5 0.5 -0.5 0.5 -1.2 0.8 C -2.3 1.2 -3 2 -3 3 Z"
        fill={color}
      />
    );
  }
  if (nodeKey === "inventory") {
    // Inventory stack / reel
    return (
      <g stroke={color} strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round">
        <rect x="-6" y="-5" width="12" height="10" rx="2" />
        <line x1="-3" y1="-5" x2="-3" y2="5" />
        <line x1="3" y1="-5" x2="3" y2="5" />
      </g>
    );
  }
  if (nodeKey === "ai_metadata") {
    // Sparkles
    return (
      <g fill={color}>
        <path d="M 0 -6 L 1.5 -1.5 L 6 0 L 1.5 1.5 L 0 6 L -1.5 1.5 L -6 0 L -1.5 -1.5 Z" />
        <path d="M 4 -4 L 4.8 -2.5 L 6.5 -2 L 5 -0.8 L 5.5 0.8 L 4 -0.2 Z" opacity="0.7" />
      </g>
    );
  }
  if (nodeKey === "scheduler") {
    // Clock
    return (
      <g stroke={color} strokeWidth="1.5" fill="none" strokeLinecap="round">
        <circle cx="0" cy="0" r="6" />
        <polyline points="0 -3.5 0 0 2.5 1.5" />
      </g>
    );
  }
  if (nodeKey === "publisher") {
    // Upload arrow
    return (
      <g stroke={color} strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round">
        <path d="M -5 3 L -5 5 C -5 5.6 -4.6 6 -4 6 L 4 6 C 4.6 6 5 5.6 5 5 L 5 3" />
        <polyline points="-3 -1 0 -4 3 -1" />
        <line x1="0" y1="-4" x2="0" y2="2" />
      </g>
    );
  }
  // YouTube Destination
  return (
    <g fill={color}>
      <rect x="-6" y="-4.5" width="12" height="9" rx="2" fill="none" stroke={color} strokeWidth="1.5" />
      <polygon points="-1.5 -2.5 2.5 0 -1.5 2.5" />
    </g>
  );
}

export function TikTokPipelineOrbitalView({
  pipelineName,
  autoPublish = true,
  live = true,
  nodes,
  activeEdges = [],
  channelAvatarUrl = null,
  channelName = null,
}: TikTokPipelineOrbitalViewProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [allowAnimation, setAllowAnimation] = useState(() => {
    if (typeof window === "undefined") return true;
    try {
      const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      const isLowEnd =
        typeof navigator !== "undefined" &&
        navigator.hardwareConcurrency != null &&
        navigator.hardwareConcurrency <= 2;
      return !reduced && !isLowEnd;
    } catch {
      return true;
    }
  });

  // Listen to prefers-reduced-motion media query changes
  useEffect(() => {
    if (typeof window === "undefined") return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const handler = (e: MediaQueryListEvent) => {
      setAllowAnimation(!e.matches);
    };
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  // Pause SVG animation when browser tab is hidden to save CPU/battery
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;

    const handleVisibility = () => {
      try {
        if (document.hidden) {
          if (typeof (svg as any).pauseAnimations === "function") {
            (svg as any).pauseAnimations();
          }
        } else {
          if (typeof (svg as any).unpauseAnimations === "function") {
            (svg as any).unpauseAnimations();
          }
        }
      } catch {
        // SVG pause API is optional across environments
      }
    };

    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, []);

  const displayName = channelName || pipelineName || "TikTok Pipeline";
  const initialLetter = displayName.charAt(0).toUpperCase() || "T";

  return (
    <div className="rounded-2xl border border-slate-200/90 bg-white p-3.5 shadow-sm sm:p-5">
      <div className="mb-2 flex items-center justify-between border-b border-slate-100 pb-3">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            {live ? <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" /> : null}
            <span className={`relative inline-flex h-2 w-2 rounded-full ${live ? "bg-emerald-500" : "bg-slate-300"}`} />
          </span>
          <span className="text-[11px] font-extrabold uppercase tracking-wider text-slate-500">
            TikTok Pipeline Live
          </span>
        </div>
        <div className="flex items-center gap-1.5 text-[11px]">
          <span className="font-semibold text-slate-400">Mode:</span>
          <span className={`font-bold ${autoPublish ? "text-indigo-600" : "text-slate-600"}`}>
            {autoPublish ? "AUTO" : "MANUAL"}
          </span>
        </div>
      </div>

      <div className="relative w-full overflow-hidden">
        <svg
          ref={svgRef}
          viewBox="0 0 720 380"
          className="h-auto w-full max-w-full select-none"
          preserveAspectRatio="xMidYMid meet"
          aria-label="TikTok Pipeline Orbital Diagram"
        >
          {/* Orbit Track: Ellipse cx=360, cy=190, rx=250, ry=115 */}
          <path
            id="tiktok-orbit-track"
            d="M 360 75 A 250 115 0 1 1 359.9 75 Z"
            fill="none"
            stroke="#e2e8f0"
            strokeWidth="1.5"
            strokeDasharray="4 4"
          />

          {/* 1-2 small traveling dots on orbit rail (Ultra lightweight pure SVG animation) */}
          {allowAnimation ? (
            <>
              <circle r="3.5" fill="#4f46e5" className="tiktok-orbit-particle">
                <animateMotion
                  path="M 360 75 A 250 115 0 1 1 359.9 75 Z"
                  dur="14s"
                  repeatCount="indefinite"
                />
              </circle>
              <circle r="2.5" fill="#818cf8" opacity="0.8" className="tiktok-orbit-particle">
                <animateMotion
                  path="M 360 75 A 250 115 0 1 1 359.9 75 Z"
                  dur="14s"
                  begin="7s"
                  repeatCount="indefinite"
                />
              </circle>
            </>
          ) : null}

          {/* Active edge highlight if running */}
          {activeEdges && activeEdges.length > 0 ? (
            <ellipse
              cx="360"
              cy="190"
              rx="250"
              ry="115"
              fill="none"
              stroke="#818cf8"
              strokeWidth="2"
              strokeDasharray="6 8"
              opacity="0.6"
            />
          ) : null}

          {/* Center Pipeline Core */}
          <g transform="translate(360, 190)">
            {/* Outer soft ring */}
            <circle cx="0" cy="0" r="42" fill="#f8fafc" stroke="#e2e8f0" strokeWidth="2" />
            <circle cx="0" cy="0" r="34" fill="#ffffff" stroke="#c7d2fe" strokeWidth="1.5" />

            {/* Avatar or initial */}
            {channelAvatarUrl ? (
              <image
                href={channelAvatarUrl}
                x="-24"
                y="-24"
                width="48"
                height="48"
                clipPath="url(#tiktok-avatar-clip)"
                preserveAspectRatio="xMidYMid slice"
              />
            ) : (
              <g transform="translate(0, 0)">
                <circle cx="0" cy="0" r="22" fill="#4f46e5" />
                <text
                  x="0"
                  y="6"
                  textAnchor="middle"
                  fill="#ffffff"
                  fontSize="15"
                  fontWeight="800"
                  fontFamily="system-ui, -apple-system, sans-serif"
                >
                  {initialLetter}
                </text>
              </g>
            )}

            {/* Center Label below avatar */}
            <text
              x="0"
              y="54"
              textAnchor="middle"
              fill="#0f172a"
              fontSize="12"
              fontWeight="800"
              fontFamily="system-ui, -apple-system, sans-serif"
            >
              {displayName.length > 22 ? `${displayName.slice(0, 20)}…` : displayName}
            </text>

            {/* Auto status badge */}
            <rect
              x="-30"
              y="60"
              width="60"
              height="15"
              rx="7.5"
              fill={autoPublish ? "#e0e7ff" : "#f1f5f9"}
            />
            <text
              x="0"
              y="71"
              textAnchor="middle"
              fill={autoPublish ? "#4338ca" : "#64748b"}
              fontSize="8.5"
              fontWeight="700"
              fontFamily="system-ui, -apple-system, sans-serif"
            >
              {autoPublish ? "AUTO ON" : "MANUAL"}
            </text>
          </g>

          {/* Avatar clip definition */}
          <defs>
            <clipPath id="tiktok-avatar-clip">
              <circle cx="0" cy="0" r="24" />
            </clipPath>
          </defs>

          {/* 6 Surrounding Orbit Nodes */}
          {nodes.map((node, idx) => {
            const coord = NODE_COORDINATES[idx] || NODE_COORDINATES[0];
            const theme = getStatusTheme(node.status);
            const isCenterAligned = coord.align === "center";
            const isRight = coord.align === "right";
            const isLeft = coord.align === "left";

            // Card box dimensions
            const boxW = 142;
            const boxH = 46;
            const boxX = isCenterAligned ? coord.x - boxW / 2 : isRight ? coord.x - 20 : coord.x - boxW + 20;
            const boxY = coord.y - boxH / 2;

            return (
              <g key={node.key} className="transition-transform duration-200">
                {/* Node connector line from orbit to card */}
                <line
                  x1={coord.x}
                  y1={coord.y}
                  x2={isCenterAligned ? coord.x : isRight ? boxX : boxX + boxW}
                  y2={coord.y}
                  stroke="#cbd5e1"
                  strokeWidth="1"
                  strokeDasharray="2 2"
                />

                {/* Node Box */}
                <rect
                  x={boxX}
                  y={boxY}
                  width={boxW}
                  height={boxH}
                  rx="12"
                  fill="#ffffff"
                  stroke={theme.border}
                  strokeWidth="1.5"
                />

                {/* Node Icon Circle */}
                <g transform={`translate(${boxX + 22}, ${boxY + 23})`}>
                  <circle cx="0" cy="0" r="14" fill={theme.bg} />
                  <NodeIcon nodeKey={node.key} color={theme.dot} />
                </g>

                {/* Node Title & Subtitle */}
                <text
                  x={boxX + 42}
                  y={boxY + 18}
                  fill="#0f172a"
                  fontSize="11"
                  fontWeight="700"
                  fontFamily="system-ui, -apple-system, sans-serif"
                >
                  {node.title.length > 13 ? `${node.title.slice(0, 12)}…` : node.title}
                </text>
                <text
                  x={boxX + 42}
                  y={boxY + 32}
                  fill="#64748b"
                  fontSize="9.5"
                  fontWeight="500"
                  fontFamily="system-ui, -apple-system, sans-serif"
                >
                  {node.subtitle.length > 17 ? `${node.subtitle.slice(0, 16)}…` : node.subtitle}
                </text>

                {/* Status Dot / Pill */}
                <circle cx={boxX + boxW - 12} cy={boxY + 14} r="3" fill={theme.dot} />
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}
