import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function generateSessionId(): string {
  // crypto.getRandomValues rather than Math.random. This id scopes a browser's
  // view of the feed and is not a credential, so the practical risk of a
  // predictable value is nil. It is fixed anyway for two reasons: CodeQL scores
  // js/insecure-randomness as high and it was the only high-severity alert on
  // the security tab of a security product, and an id that is not a secret
  // today is exactly the kind of thing that quietly becomes one later.
  //
  // randomUUID needs a secure context, which a dashboard served over plain
  // http on a LAN address is not, so this uses getRandomValues directly and
  // falls back only where neither exists (older SSR paths, not browsers).
  const bytes = new Uint8Array(8);
  const c = globalThis.crypto;
  if (c?.getRandomValues) {
    c.getRandomValues(bytes);
  } else {
    // No secure source available. Better a visibly degraded id than a silent
    // one: a collision here shows up as a feed that will not scope, which is
    // debuggable, rather than as a security property nobody checked.
    return `session-${Date.now()}-insecure`;
  }
  const suffix = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `session-${Date.now()}-${suffix}`;
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
