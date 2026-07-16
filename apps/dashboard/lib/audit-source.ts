import type { AuditEvent } from "@/components/flight-recorder-panel";

// Trails written before the Agentmetry rename carry the legacy first-party
// name. Normalize on read so old events keep rendering under one label —
// this must happen everywhere a source is displayed, or the dead codename
// leaks into charts (which is exactly how the third copy of this logic
// drifted before it was consolidated here).
const LEGACY_SOURCE_APPS = new Set(["blackbox"]);

export const SOURCE_LABELS: Record<string, string> = {
  agentmetry: "Agentmetry",
  cursor: "Cursor",
  claude: "Claude",
  codex: "Codex",
  antigravity: "Antigravity",
  mcp_proxy: "MCP",
};

/** Light + dark Tailwind classes for source badges in the event feed. */
const SOURCE_BADGE_CLASS: Record<string, string> = {
  agentmetry:
    "bg-emerald-50 text-emerald-800 ring-1 ring-emerald-500/20 dark:bg-emerald-950/40 dark:text-emerald-300",
  cursor:
    "bg-violet-100 text-violet-800 ring-1 ring-violet-500/25 dark:bg-violet-950/50 dark:text-violet-300",
  claude:
    "bg-amber-100 text-amber-900 ring-1 ring-amber-500/25 dark:bg-amber-950/50 dark:text-amber-200",
  codex:
    "bg-cyan-100 text-cyan-900 ring-1 ring-cyan-500/25 dark:bg-cyan-950/50 dark:text-cyan-200",
  antigravity:
    "bg-fuchsia-100 text-fuchsia-900 ring-1 ring-fuchsia-500/25 dark:bg-fuchsia-950/50 dark:text-fuchsia-200",
  mcp_proxy:
    "bg-orange-100 text-orange-900 ring-1 ring-orange-500/25 dark:bg-orange-950/50 dark:text-orange-200",
};

const SOURCE_DOT_CLASS: Record<string, string> = {
  agentmetry: "bg-emerald-400",
  cursor: "bg-violet-400",
  claude: "bg-amber-400",
  codex: "bg-cyan-400",
  antigravity: "bg-fuchsia-400",
  mcp_proxy: "bg-orange-400",
};

/** Hex fills for Recharts source breakdown. */
export const SOURCE_CHART_COLOR: Record<string, string> = {
  agentmetry: "#34d399",
  cursor: "#a78bfa",
  claude: "#fbbf24",
  codex: "#22d3ee",
  antigravity: "#e879f9",
  mcp_proxy: "#fb923c",
};

const DEFAULT_BADGE_CLASS =
  "bg-slate-100 text-slate-800 ring-1 ring-slate-500/20 dark:bg-slate-900/60 dark:text-slate-300";
const DEFAULT_DOT_CLASS = "bg-slate-400";
const DEFAULT_CHART_COLOR = "#94a3b8";

export const normalizeSourceApp = (name: string): string => {
  const key = name.trim().toLowerCase();
  if (key === "mcp") return "mcp_proxy";
  return LEGACY_SOURCE_APPS.has(key) ? "agentmetry" : key;
};

export function sourceLabel(app: string): string {
  const key = normalizeSourceApp(app);
  return SOURCE_LABELS[key] || app;
}

export function sourceBadgeClass(app: string): string {
  return SOURCE_BADGE_CLASS[normalizeSourceApp(app)] ?? DEFAULT_BADGE_CLASS;
}

export function sourceDotClass(app: string, active = true): string {
  if (!active) return "bg-muted";
  return SOURCE_DOT_CLASS[normalizeSourceApp(app)] ?? DEFAULT_DOT_CLASS;
}

export function sourceChartColor(app: string): string {
  return SOURCE_CHART_COLOR[normalizeSourceApp(app)] ?? DEFAULT_CHART_COLOR;
}

export function eventSourceApp(event: AuditEvent): string {
  if (event.source?.app) return normalizeSourceApp(event.source.app);
  const agent = event.agent?.name ? normalizeSourceApp(event.agent.name) : "";
  if (agent && agent !== "agentmetry") return agent;
  return "agentmetry";
}
