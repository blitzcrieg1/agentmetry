import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function generateSessionId(): string {
  return `session-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

// When the dashboard is served as a static export by the orchestrator itself
// (single-process mode, NEXT_PUBLIC_SAME_ORIGIN=true), talk to the same origin
// the page was loaded from — this also makes LAN/phone access "just work".
// In two-terminal dev the explicit env var (or the :8000 default) is used.
const _SAME_ORIGIN =
  process.env.NEXT_PUBLIC_SAME_ORIGIN === "true" && typeof window !== "undefined";

function httpBase(): string {
  if (process.env.NEXT_PUBLIC_ORCHESTRATOR_URL) {
    return process.env.NEXT_PUBLIC_ORCHESTRATOR_URL;
  }
  if (_SAME_ORIGIN) return window.location.origin;
  return "http://localhost:8000";
}

function wsBase(): string {
  if (process.env.NEXT_PUBLIC_WS_URL) return process.env.NEXT_PUBLIC_WS_URL;
  if (_SAME_ORIGIN) {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}`;
  }
  return "ws://localhost:8000";
}

export const ORCHESTRATOR_URL = httpBase();

export const WS_URL = wsBase();
