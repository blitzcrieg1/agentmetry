import type { Detection } from "@/components/flight-recorder-panel";
import type { DogfoodReport } from "@/lib/dogfood";
import type { MachineSnapshot } from "@/lib/machine";
import { displaySource, sourceLabel } from "@/lib/audit-source";

/**
 * The Overview page's findings, worst first, each sorted into one of three kinds:
 *
 * - **health**: whether the record itself can be trusted (chain, spool, gate)
 * - **alert**: something happened that needs a decision (detections)
 * - **risk**: a configuration that could let something happen unseen or
 *   unstopped (missing or silent hooks, prompts skipped, log mode, MCP)
 *
 * Alerts and risks were one list, so "4 critical detections" sat beside
 * "policy runs in log mode" and the page read as noise.
 *
 * Every item is computed from an API field the page already fetched. An item
 * the data cannot support is left out rather than guessed: there is no anchor
 * status in the API yet, so the list does not claim the trail is unanchored.
 * Each item names where the fix lives, because a list that only says something
 * is wrong is a list people learn to skip.
 */

export type AttentionTarget = "detections" | "machine" | "analytics" | "recorder";

export type AttentionKind = "health" | "alert" | "risk";

export interface AttentionItem {
  id: string;
  kind: AttentionKind;
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
  enabled?: boolean;
  last_event_utc?: string | null;
  recent?: number;
  by_source?: Record<string, number>;
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
      kind: "health",
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
      kind: "alert",
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
      kind: "alert",
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
      kind: "health",
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
      kind: "risk",
      severity: "high",
      title: `${plural(uncovered.length, "installed agent")} not recorded`,
      body: `${uncovered.map((a) => sourceLabel(a.name)).join(", ")}. Installed here, with no Agentmetry hook. Run agentmetry hooks install.`,
      cta: "Open this machine",
      target: "machine",
    });
  }

  // Configured is not the same as recorded (#304): a hook in the config with no
  // event in seven days is either an agent nobody used or capture that broke.
  // Only judged once the 7-day stats have loaded, so a slow call never paints
  // every agent as silent.
  if (stats?.by_source && machine) {
    const silent = machine.agents.filter((a) => a.state === "covered" && eventsFor(stats.by_source, a.name) === 0);
    if (silent.length) {
      items.push({
        id: "silent",
        kind: "risk",
        severity: "medium",
        title: `${plural(silent.length, "agent")} with a hook and no events in 7 days`,
        body: `${silent.map((a) => sourceLabel(a.name)).join(", ")}. Either nobody used ${silent.length === 1 ? "it" : "them"}, or capture is broken. Run the agent once and check it arrives.`,
        cta: "Open this machine",
        target: "machine",
      });
    }
  }

  if (dogfood?.started && !dogfood.passed) {
    const red = dogfood.weeks.filter((w) => w.complete && w.verdict === "RED");
    if (red.length) {
      const untriagedInRed = red.reduce((n, w) => n + w.untriaged, 0);
      const weeks = `${red.length === 1 ? "Week" : "Weeks"} ${red.map((w) => w.index).join(" and ")} ${red.length === 1 ? "is" : "are"}`;
      items.push({
        id: "gate",
        kind: "health",
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
      kind: "risk",
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
      kind: "risk",
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
      kind: "risk",
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
      kind: "risk",
      severity: "low",
      title: `${sourceLabel(nc.agent)} settings are not checked`,
      body: `${nc.why.charAt(0).toUpperCase()}${nc.why.slice(1)}.`,
      cta: "Open this machine",
      target: "machine",
    });
  }

  return items.sort((a, b) => RANK[a.severity] - RANK[b.severity]);
}

function eventsFor(bySource: Record<string, number> | undefined, app: string): number {
  const target = displaySource(app);
  return Object.entries(bySource ?? {}).reduce((n, [source, count]) => n + (displaySource(source) === target ? count : 0), 0);
}

export interface RuleGroup {
  rule_id: string;
  title: string;
  severity: Detection["severity"];
  detections: number;
  sessions: number;
  agents: string[];
  untriaged: number;
  lastSeenUtc: string;
}

/**
 * Detections grouped by rule, the "top alerts" list: one row per rule with how
 * much it touched. Worst severity first, then the most undecided, then the
 * busiest, so the row that needs a person is the first one read.
 */
export function topRules(dets: Detection[], isOpen: (d: Detection) => boolean, limit = 5): RuleGroup[] {
  const byRule = new Map<string, { group: RuleGroup; sessions: Set<string>; agents: Set<string> }>();
  for (const d of dets) {
    let entry = byRule.get(d.rule_id);
    if (!entry) {
      entry = {
        group: { rule_id: d.rule_id, title: d.title || d.rule_id, severity: d.severity, detections: 0, sessions: 0, agents: [], untriaged: 0, lastSeenUtc: "" },
        sessions: new Set(),
        agents: new Set(),
      };
      byRule.set(d.rule_id, entry);
    }
    const g = entry.group;
    g.detections += 1;
    if (isOpen(d)) g.untriaged += 1;
    if (RANK[d.severity] < RANK[g.severity]) g.severity = d.severity;
    if ((d.last_seen_utc ?? "") > g.lastSeenUtc) g.lastSeenUtc = d.last_seen_utc ?? "";
    entry.sessions.add(d.correlation_id);
    if (d.app) entry.agents.add(d.app);
  }
  return [...byRule.values()]
    .map(({ group, sessions, agents }) => ({ ...group, sessions: sessions.size, agents: [...agents].sort() }))
    .sort((a, b) => RANK[a.severity] - RANK[b.severity] || b.untriaged - a.untriaged || b.detections - a.detections || a.rule_id.localeCompare(b.rule_id))
    .slice(0, limit);
}

/**
 * The previous 7 days, from the 7-day and 14-day stats: the 14-day count less
 * the 7-day one. Null when either is missing, so no comparison is drawn from a
 * number that did not load.
 */
export function previousWeek(week?: number | null, fortnight?: number | null): number | null {
  if (week == null || fortnight == null || fortnight < week) return null;
  return fortnight - week;
}

/** "+12 vs previous 7 days", or null when there is nothing to compare. */
export function changeSentence(week?: number | null, fortnight?: number | null): string | null {
  const prev = previousWeek(week, fortnight);
  if (prev == null || week == null) return null;
  const delta = week - prev;
  return delta === 0 ? "same as the previous 7 days" : `${delta > 0 ? "+" : "-"}${Math.abs(delta).toLocaleString()} vs the previous 7 days`;
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
