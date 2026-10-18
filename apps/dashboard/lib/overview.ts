import type { Detection } from "@/components/flight-recorder-panel";
import type { DogfoodReport } from "@/lib/dogfood";
import type { MachineSnapshot } from "@/lib/machine";
import { sourceLabel } from "@/lib/audit-source";

/**
 * The Overview page's "Needs attention" list, worst first.
 *
 * Every item is computed from an API field the page already fetched. An item
 * the data cannot support is left out rather than guessed: there is no anchor
 * status in the API yet, so the list does not claim the trail is unanchored.
 * Each item names where the fix lives, because a list that only says something
 * is wrong is a list people learn to skip.
 */

export type AttentionTarget = "detections" | "machine" | "analytics" | "recorder";

export interface AttentionItem {
  id: string;
  severity: "critical" | "high" | "medium" | "low";
  title: string;
  body: string;
  cta: string;
  target: AttentionTarget;
}

export interface StatsSnapshot {
  enabled?: boolean;
  total_events?: number;
  sessions?: number;
  detections?: number;
  denied?: number;
  dlp_matches?: number;
  tool_policy_hits?: number;
  tool_policy_blocks?: number;
  by_source?: Record<string, number>;
  last_event_utc?: string | null;
}

export interface StatusSnapshot {
  spool_pending?: number;
  spool_oldest_age_seconds?: number | null;
}

export interface OverviewInputs {
  untriaged: Detection[];
  stats: StatsSnapshot | null;
  machine: MachineSnapshot | null;
  dogfood: DogfoodReport | null;
  status: StatusSnapshot | null;
}

const RANK = { critical: 0, high: 1, medium: 2, low: 3 } as const;

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString()} ${n === 1 ? one : many}`;
}

function listTitles(dets: Detection[], max = 3): string {
  const titles = Array.from(new Set(dets.map((d) => d.title || d.rule_id)));
  const shown = titles.slice(0, max);
  const rest = titles.length - shown.length;
  return shown.join("; ") + (rest > 0 ? `; and ${plural(rest, "other")}` : "");
}

export function attentionItems({ untriaged, stats, machine, dogfood, status }: OverviewInputs): AttentionItem[] {
  const items: AttentionItem[] = [];

  if (dogfood && !dogfood.chain_ok) {
    items.push({
      id: "chain",
      severity: "critical",
      title: "The trail does not verify",
      body: dogfood.chain_message || "The hash chain check failed.",
      cta: "Open analytics",
      target: "analytics",
    });
  }

  const critical = untriaged.filter((d) => d.severity === "critical");
  const high = untriaged.filter((d) => d.severity === "high");
  if (critical.length) {
    items.push({
      id: "critical",
      severity: "critical",
      title: `${plural(critical.length, "critical detection")} with no decision`,
      body: listTitles(critical),
      cta: "Investigate",
      target: "detections",
    });
  }
  if (high.length) {
    items.push({
      id: "high",
      severity: "high",
      title: `${plural(high.length, "high detection")} with no decision`,
      body: listTitles(high),
      cta: "Investigate",
      target: "detections",
    });
  }

  const spooled = status?.spool_pending ?? dogfood?.spooled ?? 0;
  if (spooled > 0) {
    items.push({
      id: "spool",
      severity: "high",
      title: `${plural(spooled, "event")} waiting in the hook spool`,
      body: "The hooks recorded them while the recorder could not be reached. They reach the trail, and the detections, when it replays them.",
      cta: "Open the event stream",
      target: "recorder",
    });
  }

  const uncovered = machine?.agents.filter((a) => a.state === "uncovered") ?? [];
  if (uncovered.length) {
    items.push({
      id: "uncovered",
      severity: "high",
      title: `${plural(uncovered.length, "installed agent")} not recorded`,
      body: `${uncovered.map((a) => sourceLabel(a.name)).join(", ")}. Installed here, with no Agentmetry hook. Run agentmetry hooks install.`,
      cta: "Open this machine",
      target: "machine",
    });
  }

  if (dogfood?.started && !dogfood.passed) {
    const red = dogfood.weeks.filter((w) => w.complete && w.verdict === "RED");
    if (red.length) {
      const untriagedInRed = red.reduce((n, w) => n + w.untriaged, 0);
      const weeks = `${red.length === 1 ? "Week" : "Weeks"} ${red.map((w) => w.index).join(" and ")} ${red.length === 1 ? "is" : "are"}`;
      items.push({
        id: "gate",
        severity: "high",
        title: `The beta gate is at ${dogfood.consecutive_green} of ${dogfood.required}`,
        body:
          untriagedInRed > 0
            ? `${weeks} red on ${plural(untriagedInRed, "detection")} nobody has dispositioned. Triaging them turns ${red.length === 1 ? "it" : "them"} green.`
            : `${weeks} red: ${red[0].reasons[0] ?? "see the gate"}.`,
        cta: "Open the gate",
        target: "analytics",
      });
    }
  }

  const postureHigh = machine?.posture.counts.high ?? 0;
  const postureMedium = machine?.posture.counts.medium ?? 0;
  if (postureHigh + postureMedium > 0) {
    items.push({
      id: "posture",
      severity: postureHigh ? "high" : "medium",
      title: `${plural(postureHigh + postureMedium, "agent setting")} that skip a prompt`,
      body: "An agent is configured to run tools without asking. The settings check names the file and the line.",
      cta: "Open this machine",
      target: "machine",
    });
  }

  const matches = (stats?.tool_policy_hits ?? 0) + (stats?.dlp_matches ?? 0);
  if (machine && machine.policy.mode !== "block" && matches > 0) {
    items.push({
      id: "logmode",
      severity: "medium",
      title: "Policy runs in log mode",
      body: `${plural(stats?.tool_policy_hits ?? 0, "tool policy match", "tool policy matches")} and ${plural(stats?.dlp_matches ?? 0, "DLP match", "DLP matches")} in 7 days were recorded, and the calls still ran.`,
      cta: "Open this machine",
      target: "machine",
    });
  }

  const unseen = machine?.mcp.servers.filter((s) => s.listing === "not_observed") ?? [];
  if (unseen.length) {
    items.push({
      id: "mcp",
      severity: "medium",
      title: `${plural(unseen.length, "MCP server")} not seen through the proxy`,
      body: `${unseen.map((s) => `${s.name} (${sourceLabel(s.agent)})`).join(", ")}. The tools the model was handed are unknown.`,
      cta: "Open this machine",
      target: "machine",
    });
  }

  for (const nc of machine?.posture.not_checked ?? []) {
    items.push({
      id: `nc-${nc.agent}`,
      severity: "low",
      title: `${sourceLabel(nc.agent)} settings are not checked`,
      body: `${nc.why.charAt(0).toUpperCase()}${nc.why.slice(1)}.`,
      cta: "Open this machine",
      target: "machine",
    });
  }

  return items.sort((a, b) => RANK[a.severity] - RANK[b.severity]);
}

/** Events per agent for the bar list, busiest first, with each bar's share of the busiest. */
export function sourceBars(bySource: Record<string, number> | undefined): { app: string; n: number; pct: number }[] {
  const rows = Object.entries(bySource ?? {})
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1]);
  const max = rows[0]?.[1] ?? 0;
  return rows.map(([app, n]) => ({ app, n, pct: max ? Math.max(1, Math.round((n / max) * 100)) : 0 }));
}

/** Technique ids across detections, most frequent first. */
export function techniqueCounts(dets: Detection[]): { id: string; n: number }[] {
  const counts = new Map<string, number>();
  for (const d of dets) for (const t of d.technique_ids ?? []) counts.set(t, (counts.get(t) ?? 0) + 1);
  return Array.from(counts, ([id, n]) => ({ id, n })).sort((a, b) => b.n - a.n || a.id.localeCompare(b.id));
}
