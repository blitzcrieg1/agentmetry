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

// A production build is the static export the orchestrator serves, on :8000
// (`scripts/serve.bat`) or on :8010 (`scripts/demo_dashboard.py`) or on a LAN
// address. Relative URLs follow that page. `next dev` stays on :8000, because
// the Next server is :3000 and is not the API. An explicit
// NEXT_PUBLIC_ORCHESTRATOR_URL still wins, for a split deploy.
//
// The production string is empty on the server and in the browser, so the
// evidence-pack link does not hydrate to a different host. The old
// NEXT_PUBLIC_SAME_ORIGIN flag depended on `window` and was false during
// prerender, and a plain `npm run build` never set it.

export type OrchestratorLocation = {
  configuredUrl?: string;
  nodeEnv?: string;
  sameOriginFlag?: boolean;
  pageOrigin?: string | null;
};

function wantsSameOrigin(nodeEnv: string | undefined, flag: boolean | undefined): boolean {
  if (flag !== undefined) return flag;
  return nodeEnv === "production" || process.env.NEXT_PUBLIC_SAME_ORIGIN === "true";
}

export function orchestratorHttpBase(loc: OrchestratorLocation = {}): string {
  const configured = loc.configuredUrl ?? process.env.NEXT_PUBLIC_ORCHESTRATOR_URL;
  if (configured) return configured.replace(/\/$/, "");
  const nodeEnv = loc.nodeEnv ?? process.env.NODE_ENV;
  if (!wantsSameOrigin(nodeEnv, loc.sameOriginFlag)) return "http://localhost:8000";
  if (nodeEnv === "production") return "";
  if (loc.pageOrigin) return loc.pageOrigin.replace(/\/$/, "");
  if (typeof window !== "undefined") return window.location.origin;
  return "";
}

export type OrchestratorSocket = {
  configuredUrl?: string;
  nodeEnv?: string;
  sameOriginFlag?: boolean;
  pageProtocol?: string | null;
  pageHost?: string | null;
};

export function orchestratorWsBase(loc: OrchestratorSocket = {}): string {
  const configured = loc.configuredUrl ?? process.env.NEXT_PUBLIC_WS_URL;
  if (configured) return configured.replace(/\/$/, "");
  const nodeEnv = loc.nodeEnv ?? process.env.NODE_ENV;
  const protocol = loc.pageProtocol ?? (typeof window !== "undefined" ? window.location.protocol : null);
  const host = loc.pageHost ?? (typeof window !== "undefined" ? window.location.host : null);
  if (wantsSameOrigin(nodeEnv, loc.sameOriginFlag) && protocol && host) {
    const wsProto = protocol === "https:" ? "wss:" : "ws:";
    return `${wsProto}//${host}`;
  }
  return "ws://localhost:8000";
}

export const ORCHESTRATOR_URL = orchestratorHttpBase();

export const WS_URL = orchestratorWsBase();
