import type { PointerEvent } from "react";

/** The most a tile leans, in degrees. Enough to read as depth, not as motion. */
export const MAX_TILT = 5;

/**
 * Rotation for a pointer at (x, y) inside a box of width w and height h: the
 * tile leans toward the pointer, flat at the centre, `max` degrees at an edge.
 */
export function tiltFor(x: number, y: number, w: number, h: number, max = MAX_TILT): { rx: number; ry: number } {
  if (w <= 0 || h <= 0) return { rx: 0, ry: 0 };
  const px = Math.min(1, Math.max(0, x / w)) - 0.5;
  const py = Math.min(1, Math.max(0, y / h)) - 0.5;
  const round = (n: number) => Math.round(n * 100) / 100 || 0;
  return { rx: round(-py * 2 * max), ry: round(px * 2 * max) };
}

function reducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
}

/**
 * Pointer handlers that set `--rx` and `--ry` on the element for the `.tilt`
 * class. Writing CSS variables rather than React state keeps the pointer from
 * re-rendering the page sixty times a second.
 */
export function tiltHandlers() {
  return {
    onPointerMove(e: PointerEvent<HTMLElement>) {
      if (e.pointerType !== "mouse" || reducedMotion()) return;
      const box = e.currentTarget.getBoundingClientRect();
      const { rx, ry } = tiltFor(e.clientX - box.left, e.clientY - box.top, box.width, box.height);
      e.currentTarget.style.setProperty("--rx", `${rx}deg`);
      e.currentTarget.style.setProperty("--ry", `${ry}deg`);
    },
    onPointerLeave(e: PointerEvent<HTMLElement>) {
      e.currentTarget.style.setProperty("--rx", "0deg");
      e.currentTarget.style.setProperty("--ry", "0deg");
    },
  };
}
