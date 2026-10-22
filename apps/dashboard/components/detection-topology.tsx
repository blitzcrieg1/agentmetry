"use client";

import { useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { ArrowUpRight, RotateCcw } from "lucide-react";
import type { Detection } from "@/components/flight-recorder-panel";
import { SeverityBadge } from "@/components/ui/kit";
import { sourceLabel } from "@/lib/audit-source";

type Point3 = { x: number; y: number; z: number };
type MapFilter = "all" | "open";

const SEVERITY_LEVEL: Record<Detection["severity"], number> = {
  low: 0.22,
  medium: 0.43,
  high: 0.68,
  critical: 0.94,
};
const SEVERITY_CLASS: Record<Detection["severity"], string> = {
  low: "fill-subtle",
  medium: "fill-caution",
  high: "fill-signal",
  critical: "fill-danger",
};

function project(point: Point3, yaw: number, elevation: number): { x: number; y: number } {
  const cy = Math.cos(yaw);
  const sy = Math.sin(yaw);
  const ce = Math.cos(elevation);
  const se = Math.sin(elevation);
  const rx = point.x * cy - point.z * sy;
  const rz = point.x * sy + point.z * cy;
  const ry = point.y * ce - rz * se;
  const depth = point.y * se + rz * ce;
  const perspective = 1 / (1 + depth * 0.055);
  return {
    x: 500 + rx * 350 * perspective,
    y: 272 - ry * 112 * perspective,
  };
}

function timestampLabel(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown time";
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function DetectionTopology({
  detections,
  isOpen,
  onInvestigate,
}: {
  detections: Detection[];
  isOpen: (detection: Detection) => boolean;
  onInvestigate: (detection: Detection) => void;
}) {
  const [filter, setFilter] = useState<MapFilter>("all");
  const [yaw, setYaw] = useState(-0.36);
  const [elevation, setElevation] = useState(0.48);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const drag = useRef<{ x: number; y: number; yaw: number; elevation: number } | null>(null);

  const points = useMemo(() => {
    const ordered = [...detections]
      .filter((d) => filter === "all" || isOpen(d))
      .sort((a, b) => a.first_seen_utc.localeCompare(b.first_seen_utc))
      .slice(-48);
    const times = ordered.map((d) => Date.parse(d.first_seen_utc)).filter(Number.isFinite);
    // No clock read here: render must be pure, and an empty map draws no points.
    const minTime = times.length ? Math.min(...times) : 0;
    const maxTime = Math.max(...times, minTime + 60_000);
    const agents = [...new Set(ordered.map((d) => sourceLabel(d.app ?? "Unknown agent")))].sort();
    const laneFor = new Map(agents.map((agent, index) => [agent, agents.length <= 1 ? 0 : -0.76 + (1.52 * index) / (agents.length - 1)]));
    return ordered.map((d, index) => {
      const parsed = Date.parse(d.first_seen_utc);
      const time = Number.isFinite(parsed) ? parsed : minTime;
      const jitter = ordered.length > 1 && minTime === maxTime ? ((index % 5) - 2) * 0.018 : 0;
      return {
        detection: d,
        key: `${d.correlation_id}:${d.rule_id}:${d.first_seen_utc}`,
        agent: sourceLabel(d.app ?? "Unknown agent"),
        point: {
          x: -0.94 + (0.0 + (time - minTime) / Math.max(60_000, maxTime - minTime)) * 1.88 + jitter,
          y: SEVERITY_LEVEL[d.severity],
          z: laneFor.get(sourceLabel(d.app ?? "Unknown agent")) ?? 0,
        },
      };
    });
  }, [detections, filter, isOpen]);

  const agents = useMemo(() => [...new Set(points.map((item) => item.agent))], [points]);
  const selected = points.find((item) => item.key === selectedId) ?? null;

  const resetView = () => {
    setYaw(-0.36);
    setElevation(0.48);
  };

  const onPointerDown = (event: ReactPointerEvent<SVGSVGElement>) => {
    const target = event.target;
    if (target instanceof Element && target.closest("[data-map-point]")) return;
    drag.current = { x: event.clientX, y: event.clientY, yaw, elevation };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const onPointerMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (!drag.current) return;
    setYaw(Math.max(-1.2, Math.min(1.2, drag.current.yaw + (event.clientX - drag.current.x) * 0.006)));
    setElevation(Math.max(0.22, Math.min(0.9, drag.current.elevation + (event.clientY - drag.current.y) * 0.004)));
  };

  const endDrag = () => {
    drag.current = null;
  };

  const floor = [
    project({ x: -1.05, y: 0, z: -0.92 }, yaw, elevation),
    project({ x: 1.05, y: 0, z: -0.92 }, yaw, elevation),
    project({ x: 1.05, y: 0, z: 0.92 }, yaw, elevation),
    project({ x: -1.05, y: 0, z: 0.92 }, yaw, elevation),
  ];

  return (
    <section className="panel min-w-0 overflow-hidden" aria-label="Optional 3D investigation map">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-[15px] font-semibold">Investigation map</h2>
            <span className="rounded-full border border-border px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.06em] text-subtle">3D view</span>
          </div>
          <p className="mt-1 text-[12px] text-muted-foreground">Time runs left to right, severity rises vertically, and each agent has its own lane.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex rounded-md border border-border p-0.5" aria-label="Map filter">
            {(["all", "open"] as const).map((value) => (
              <button
                key={value}
                type="button"
                aria-pressed={filter === value}
                onClick={() => { setFilter(value); setSelectedId(null); }}
                className={`rounded px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.06em] transition-colors ${filter === value ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground"}`}
              >
                {value === "all" ? "All" : "Open"}
              </button>
            ))}
          </div>
          <button type="button" className="btn" onClick={resetView} aria-label="Reset map angle">
            <RotateCcw className="h-3.5 w-3.5" />
            Reset view
          </button>
        </div>
      </header>

      <div className="relative border-b border-border bg-background/50 px-3 py-2 sm:px-5">
        {points.length ? (
          <svg
            viewBox="0 0 1000 360"
            role="group"
            aria-label="Interactive perspective map. Drag the background to rotate. Select a point to inspect a detection."
            className="block h-[260px] w-full touch-none select-none sm:h-[330px]"
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={endDrag}
            onPointerCancel={endDrag}
          >
            <polygon points={floor.map((p) => `${p.x},${p.y}`).join(" ")} fill="hsl(var(--muted) / 0.22)" stroke="hsl(var(--border))" strokeWidth="1" />
            {[-0.72, -0.36, 0, 0.36, 0.72].map((x) => {
              const a = project({ x, y: 0, z: -0.92 }, yaw, elevation);
              const b = project({ x, y: 0, z: 0.92 }, yaw, elevation);
              return <line key={`x-${x}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="hsl(var(--border))" strokeOpacity="0.72" strokeWidth="1" />;
            })}
            {[-0.92, -0.46, 0, 0.46, 0.92].map((z) => {
              const a = project({ x: -1.05, y: 0, z }, yaw, elevation);
              const b = project({ x: 1.05, y: 0, z }, yaw, elevation);
              return <line key={`z-${z}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="hsl(var(--border))" strokeOpacity="0.72" strokeWidth="1" />;
            })}
            {[0.22, 0.43, 0.68, 0.94].map((level, index) => {
              const p = project({ x: -1.05, y: level, z: 0.92 }, yaw, elevation);
              return (
                <g key={level} aria-hidden="true">
                  <line x1={p.x} y1={p.y} x2={p.x + 18} y2={p.y} stroke="hsl(var(--border))" strokeWidth="1" />
                  <text x={p.x - 8} y={p.y + 4} textAnchor="end" className="fill-muted-foreground" fontSize="10">{["Low", "Medium", "High", "Critical"][index]}</text>
                </g>
              );
            })}
            {agents.map((agent, index) => {
              const z = agents.length <= 1 ? 0 : -0.76 + (1.52 * index) / (agents.length - 1);
              const p = project({ x: 1.04, y: 0, z }, yaw, elevation);
              return <text key={agent} x={p.x + 9} y={p.y + 4} className="fill-muted-foreground" fontSize="10">{agent.length > 15 ? `${agent.slice(0, 14)}…` : agent}</text>;
            })}
            {points.map(({ detection, key, point, agent }) => {
              const top = project(point, yaw, elevation);
              const base = project({ ...point, y: 0 }, yaw, elevation);
              const active = key === selectedId;
              const severityTone = detection.severity === "critical" ? "danger" : detection.severity === "high" ? "signal" : detection.severity === "medium" ? "caution" : "subtle";
              return (
                <g
                  key={key}
                  data-map-point
                  role="button"
                  tabIndex={0}
                  aria-label={`${detection.severity} detection: ${detection.title}, ${agent}, ${timestampLabel(detection.first_seen_utc)}`}
                  aria-pressed={active}
                  onClick={() => setSelectedId(key)}
                  onPointerUp={(event) => { event.stopPropagation(); setSelectedId(key); }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setSelectedId(key); }
                  }}
                  className="cursor-pointer outline-none"
                >
                  <title>{`${detection.title} · ${detection.severity} · ${agent}`}</title>
                  <line x1={base.x} y1={base.y} x2={top.x} y2={top.y} stroke={`hsl(var(--${detection.severity === "critical" ? "danger" : detection.severity === "high" ? "signal" : detection.severity === "medium" ? "caution" : "subtle"}) / ${active ? "0.9" : "0.42"})`} strokeWidth={active ? "2" : "1.25"} />
                  <circle cx={top.x} cy={top.y} r={active ? 12 : 9} fill="hsl(var(--background))" stroke={`hsl(var(--${severityTone}))`} strokeWidth={active ? 3 : 2} />
                  <circle cx={top.x} cy={top.y} r={active ? 6 : 4.5} className={SEVERITY_CLASS[detection.severity]} />
                  <circle cx={top.x} cy={top.y} r="15" fill="transparent" />
                </g>
              );
            })}
            <text x="500" y="345" textAnchor="middle" className="fill-muted-foreground" fontSize="10">OLDER  ←  EVENT TIME  →  NEWER</text>
            <text x="954" y="24" textAnchor="end" className="fill-muted-foreground" fontSize="10">DRAG TO ROTATE · SELECT A POINT</text>
          </svg>
        ) : (
          <div className="grid h-[260px] place-items-center text-center sm:h-[330px]">
            <div>
              <p className="text-[13px] font-medium">No detections in this view</p>
              <p className="mt-1 text-[12px] text-muted-foreground">New detections will appear here by time, severity, and agent.</p>
            </div>
          </div>
        )}
      </div>

      <footer className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[11px] text-muted-foreground">
          <span>{points.length} of {detections.length} detections shown</span>
          <span className="flex items-center gap-3" aria-label="Severity legend">
            {(["critical", "high", "medium", "low"] as const).map((severity) => (
              <span key={severity} className="inline-flex items-center gap-1.5 capitalize">
                <span className={`h-2 w-2 rounded-full ${severity === "critical" ? "bg-danger" : severity === "high" ? "bg-signal" : severity === "medium" ? "bg-caution" : "bg-subtle"}`} />
                {severity}
              </span>
            ))}
          </span>
        </div>
        {selected ? (
          <div className="flex min-w-0 flex-wrap items-center justify-end gap-2.5">
            <SeverityBadge severity={selected.detection.severity} />
            <span className="max-w-[22rem] truncate text-[12px] font-medium" title={selected.detection.title}>{selected.detection.title}</span>
            <span className="text-[11px] text-muted-foreground">{selected.agent} · {timestampLabel(selected.detection.first_seen_utc)}</span>
            <button type="button" className="btn" onClick={() => onInvestigate(selected.detection)}>
              Investigate detection <ArrowUpRight className="h-3.5 w-3.5" />
            </button>
          </div>
        ) : (
          <span className="text-[11px] text-muted-foreground">Select a point to inspect it</span>
        )}
      </footer>
    </section>
  );
}
