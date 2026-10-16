"use client";

import { useEffect, useRef } from "react";
import { sourceChartColor, sourceLabel } from "@/lib/audit-source";
import {
  CUBE_FACES,
  cubeVertices,
  hitAgent,
  layoutAgents,
  project,
  rotate,
  type LaidOut,
  type SceneAgent,
  type Vec3,
} from "@/lib/machine-scene";

type Props = {
  agents: SceneAgent[];
  selected: string | null;
  onSelect: (name: string | null) => void;
};

const FACE_SHADE = [0.55, 0.72, 0.48, 0.9, 0.38, 1];

function hsl(varName: string, alpha = 1): string {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
  return `hsl(${raw} / ${alpha})`;
}

function shadeHex(hex: string, amount: number, alpha: number): string {
  const n = hex.replace("#", "");
  const r = parseInt(n.slice(0, 2), 16);
  const g = parseInt(n.slice(2, 4), 16);
  const b = parseInt(n.slice(4, 6), 16);
  const f = (c: number) => Math.round(Math.min(255, Math.max(0, c * amount)));
  return `rgba(${f(r)}, ${f(g)}, ${f(b)}, ${alpha})`;
}

function drawCube(
  ctx: CanvasRenderingContext2D,
  center: Vec3,
  size: number,
  yaw: number,
  pitch: number,
  width: number,
  height: number,
  fill: string,
  alpha: number,
) {
  const corners = cubeVertices(center, size).map((p) => project(rotate(p, yaw, pitch), width, height));
  const faces = CUBE_FACES.map((indices, i) => {
    const pts = indices.map((idx) => corners[idx]);
    const depth = pts.reduce((sum, p) => sum + p.depth, 0) / pts.length;
    return { pts, depth, shade: FACE_SHADE[i] };
  }).sort((a, b) => b.depth - a.depth);
  for (const face of faces) {
    ctx.beginPath();
    ctx.moveTo(face.pts[0].x, face.pts[0].y);
    for (let i = 1; i < face.pts.length; i++) ctx.lineTo(face.pts[i].x, face.pts[i].y);
    ctx.closePath();
    ctx.fillStyle = shadeHex(fill.startsWith("#") ? fill : "#888888", face.shade, alpha);
    ctx.fill();
    ctx.strokeStyle = hsl("--foreground", 0.18);
    ctx.lineWidth = 1;
    ctx.stroke();
  }
}

function drawScene(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  agents: LaidOut[],
  yaw: number,
  pitch: number,
  selected: string | null,
  hover: string | null,
) {
  ctx.clearRect(0, 0, width, height);
  const host = project(rotate({ x: 0, y: 0, z: 0 }, yaw, pitch), width, height);
  const ring = agents
    .map((agent) => {
      const pos = rotate(agent.position, yaw, pitch);
      return { agent, pos, drawn: project(pos, width, height) };
    })
    .sort((a, b) => b.drawn.depth - a.drawn.depth);

  ctx.strokeStyle = hsl("--border", 0.9);
  ctx.lineWidth = 1;
  for (const item of ring) {
    ctx.beginPath();
    ctx.moveTo(host.x, host.y);
    ctx.lineTo(item.drawn.x, item.drawn.y);
    ctx.stroke();
  }

  drawCube(ctx, { x: 0, y: 0, z: 0 }, 0.55, yaw, pitch, width, height, "#8a837c", 1);

  ctx.font = "11px 'IBM Plex Mono', ui-monospace, monospace";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";

  for (const item of ring) {
    const active = item.agent.name === selected || item.agent.name === hover;
    const alpha = item.agent.state === "absent" ? 0.28 : item.agent.state === "unknown" ? 0.55 : 1;
    const size = active ? 0.42 : 0.34;
    drawCube(
      ctx,
      item.agent.position,
      size,
      yaw,
      pitch,
      width,
      height,
      sourceChartColor(item.agent.name),
      alpha,
    );
    const label = sourceLabel(item.agent.name);
    ctx.fillStyle = hsl("--foreground", item.agent.state === "absent" ? 0.45 : 0.92);
    ctx.fillText(label, item.drawn.x, item.drawn.y + 16 * item.drawn.scale);
  }

  ctx.fillStyle = hsl("--subtle", 1);
  ctx.font = "10px 'IBM Plex Sans', ui-sans-serif, sans-serif";
  ctx.fillText("this host", host.x, host.y + 22 * host.scale);
}

export function MachineScene({ agents, selected, onSelect }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const yaw = useRef(0.55);
  const pitch = useRef(0.35);
  const drag = useRef<{ x: number; y: number; yaw: number; pitch: number } | null>(null);
  const hover = useRef<string | null>(null);
  const reduced = useRef(false);
  const laidOut = useRef<LaidOut[]>([]);

  useEffect(() => {
    laidOut.current = layoutAgents(agents);
  }, [agents]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    reduced.current = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let frame = 0;
    let running = true;

    const fit = () => {
      const rect = wrap.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.max(1, Math.floor(rect.width * dpr));
      canvas.height = Math.max(1, Math.floor(rect.height * dpr));
      canvas.style.width = `${rect.width}px`;
      canvas.style.height = `${rect.height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(wrap);

    const cssSize = () => {
      const rect = wrap.getBoundingClientRect();
      return { w: rect.width, h: rect.height };
    };

    const paint = () => {
      if (!running) return;
      if (!reduced.current && !drag.current) yaw.current += 0.004;
      const { w, h } = cssSize();
      drawScene(ctx, w, h, laidOut.current, yaw.current, pitch.current, selected, hover.current);
      frame = requestAnimationFrame(paint);
    };
    frame = requestAnimationFrame(paint);

    const local = (event: PointerEvent) => {
      const rect = canvas.getBoundingClientRect();
      return { x: event.clientX - rect.left, y: event.clientY - rect.top };
    };

    const onDown = (event: PointerEvent) => {
      canvas.setPointerCapture(event.pointerId);
      const p = local(event);
      drag.current = { x: p.x, y: p.y, yaw: yaw.current, pitch: pitch.current };
    };
    const onMove = (event: PointerEvent) => {
      const { w, h } = cssSize();
      const p = local(event);
      if (drag.current) {
        yaw.current = drag.current.yaw + (p.x - drag.current.x) * 0.008;
        pitch.current = Math.max(-1.1, Math.min(1.1, drag.current.pitch + (p.y - drag.current.y) * 0.008));
      }
      hover.current = hitAgent(laidOut.current, yaw.current, pitch.current, w, h, p.x, p.y);
      canvas.style.cursor = hover.current ? "pointer" : drag.current ? "grabbing" : "grab";
    };
    const onUp = (event: PointerEvent) => {
      const start = drag.current;
      drag.current = null;
      if (!start) return;
      const p = local(event);
      const moved = Math.hypot(p.x - start.x, p.y - start.y);
      if (moved > 6) return;
      const { w, h } = cssSize();
      const name = hitAgent(laidOut.current, yaw.current, pitch.current, w, h, p.x, p.y);
      onSelect(name && name === selected ? null : name);
    };
    const onLeave = () => {
      hover.current = null;
      drag.current = null;
      canvas.style.cursor = "grab";
    };

    canvas.addEventListener("pointerdown", onDown);
    canvas.addEventListener("pointermove", onMove);
    canvas.addEventListener("pointerup", onUp);
    canvas.addEventListener("pointerleave", onLeave);
    window.addEventListener("resize", fit);

    return () => {
      running = false;
      cancelAnimationFrame(frame);
      ro.disconnect();
      canvas.removeEventListener("pointerdown", onDown);
      canvas.removeEventListener("pointermove", onMove);
      canvas.removeEventListener("pointerup", onUp);
      canvas.removeEventListener("pointerleave", onLeave);
      window.removeEventListener("resize", fit);
    };
  }, [onSelect, selected]);

  return (
    <div className="panel shrink-0 overflow-hidden">
      <div ref={wrapRef} className="relative h-[280px] xl:h-[320px]">
        <canvas
          ref={canvasRef}
          className="h-full w-full cursor-grab touch-none"
          role="img"
          aria-label="This host and the agents installed on it. Drag to turn. Click an agent."
        />
      </div>
      <p className="border-t border-border px-4 py-2.5 text-[12px] leading-snug text-muted-foreground">
        Drag to turn. Click an agent. This page is the hooked coding agents on this host. A CrewAI
        or OpenSRE run records through an adapter. A browser chat does not.
      </p>
    </div>
  );
}
