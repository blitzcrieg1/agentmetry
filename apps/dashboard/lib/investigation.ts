import {
  type Branch,
  type Family,
  type SessionNode,
  buildBranches,
  isCited,
  isFlagged,
  shortTool,
  toolFamily,
} from "@/lib/session-tree";

/**
 * The model behind a detection's investigation views: the hierarchy the tree
 * and graph draw, the per-category counters the table shows, and the words
 * each recorded call is described with.
 *
 * The hierarchy is machine, agent, session, tool category, call. It is the
 * tool-boundary analogue of an EDR process tree and nothing more: the hooks see
 * the calls an agent makes, not the operating system's process table, so no
 * level of it is a parent process. Every view that draws it says so.
 */

export type Signal = "cited" | "refused" | "dlp" | "policy" | "error";

/** The one signal a row leads with, strongest first. */
export function signalOf(node: SessionNode, cited: Set<string>): Signal | null {
  if (isCited(node, cited)) return "cited";
  if (node.kind === "denied") return "refused";
  if (node.dlp?.rule_id) return "dlp";
  if (node.tool_policy?.rule_id) return "policy";
  if (node.outcome === "error") return "error";
  return null;
}

export const SIGNAL_LABEL: Record<Signal, string> = {
  cited: "Cited evidence",
  refused: "Refused",
  dlp: "DLP match",
  policy: "Policy match",
  error: "Error",
};

export function kindLabel(node: SessionNode): string {
  switch (node.kind) {
    case "denied":
      return "Asked, refused";
    case "ask":
      return node.approval === "expired" ? "Asked, the session ended first" : "Asked, no call recorded";
    case "subagent_start":
      return "Subagent started";
    case "subagent_stop":
      return "Subagent finished";
    case "call":
      return node.approval ? "Asked, then ran" : "Tool call";
    case "session_start":
      return "Session started";
    case "session_end":
      return "Session ended";
    default: {
      // The tree endpoint passes any other action type through as the kind.
      const words = node.kind.replace(/_/g, " ");
      return words ? words[0].toUpperCase() + words.slice(1) : "Event";
    }
  }
}

export function policySentence(node: SessionNode): string | null {
  const p = node.tool_policy;
  if (!p?.rule_id) return null;
  if (p.mode === "block" && p.blocked) return `Stopped by ${p.rule_id} before it ran.`;
  if (p.blocked) return `Matched ${p.rule_id}. Policy is in ${p.mode ?? "log"} mode, so the call still ran.`;
  return `Matched ${p.rule_id} (${p.action ?? "rule"}, ${p.mode ?? "log"} mode).`;
}

export function dlpSentence(node: SessionNode): string | null {
  const d = node.dlp;
  if (!d?.rule_id) return null;
  const tail = d.mode === "block" ? "It was stopped before it ran." : "DLP is in log mode, so the call still ran.";
  return `DLP rule ${d.rule_id}${d.category ? ` (${d.category})` : ""} matched. ${tail}`;
}

// --- per-category counters (the activity table) ------------------------------------

export interface FamilyCount {
  key: string;
  label: string;
  family: Family;
  calls: number;
  cited: number;
  flagged: number;
  refused: number;
  errors: number;
  asked: number;
  firstUtc: string;
  lastUtc: string;
  nodes: SessionNode[];
}

/**
 * One row per tool category with the counters the table shows. Session events
 * (start, end and anything else that is not a tool) get their own row, so the
 * table accounts for every recorded event and the totals add up.
 */
export function familyCounts(nodes: SessionNode[], cited: Set<string>): FamilyCount[] {
  const byKey = new Map<string, FamilyCount>();
  for (const node of nodes) {
    if (node.kind === "detection") continue;
    const fam = toolFamily(node);
    let row = byKey.get(fam.key);
    if (!row) {
      row = { ...fam, calls: 0, cited: 0, flagged: 0, refused: 0, errors: 0, asked: 0, firstUtc: node.timestamp_utc, lastUtc: node.timestamp_utc, nodes: [] };
      byKey.set(fam.key, row);
    }
    row.calls += 1;
    row.nodes.push(node);
    if (isCited(node, cited)) row.cited += 1;
    if (isFlagged(node)) row.flagged += 1;
    if (node.kind === "denied") row.refused += 1;
    if (node.outcome === "error") row.errors += 1;
    if (node.approval) row.asked += 1;
    if (node.timestamp_utc < row.firstUtc) row.firstUtc = node.timestamp_utc;
    if (node.timestamp_utc > row.lastUtc) row.lastUtc = node.timestamp_utc;
  }
  return [...byKey.values()].sort(
    (a, b) => b.cited - a.cited || b.flagged - a.flagged || b.calls - a.calls || a.label.localeCompare(b.label),
  );
}

// --- highlight ------------------------------------------------------------------

export type Highlight = "cited" | "flagged" | "errors";

export function matchesHighlight(node: SessionNode, cited: Set<string>, highlight: Highlight | null): boolean {
  if (!highlight) return true;
  if (highlight === "cited") return isCited(node, cited);
  if (highlight === "flagged") return isFlagged(node);
  return node.outcome === "error";
}

// --- the hierarchy the tree and graph draw ---------------------------------------

export type EntityKind = "machine" | "agent" | "session" | "family" | "call" | "more";

export interface Entity {
  id: string;
  kind: EntityKind;
  label: string;
  sub?: string;
  parent?: string;
  family?: Family;
  familyKey?: string;
  node?: SessionNode;
  /** Calls in a category, or calls folded into a "more" entity. */
  count?: number;
  cited?: number;
  flagged?: number;
  signal?: Signal | null;
}

export interface HierarchyOptions {
  host: string;
  app: string;
  appLabel: string;
  adapter: string;
  sessionId: string;
  hidden: ReadonlySet<string>;
  expanded: ReadonlySet<string>;
  selectedId: string | null;
  /** Calls drawn per category before the rest fold into one "more" entity. */
  perFamily?: number;
}

export const MACHINE_ID = "machine";
export const AGENT_ID = "agent";
export const SESSION_ID = "session";

/**
 * Machine, agent, session, one entity per tool category, then the calls.
 *
 * A category shows its cited and flagged calls, the selected one, and then the
 * earliest others up to `perFamily`; the rest fold into one "more" entity that
 * expands the category. A long session drawn whole is a wall nobody reads, and
 * the fold never hides a call the detection cites.
 */
export function buildHierarchy(nodes: SessionNode[], cited: Set<string>, opts: HierarchyOptions): Entity[] {
  const perFamily = opts.perFamily ?? 8;
  const out: Entity[] = [
    { id: MACHINE_ID, kind: "machine", label: opts.host || "This machine", sub: "Machine" },
    { id: AGENT_ID, kind: "agent", label: opts.appLabel || "Agent", sub: opts.adapter || "Agent", parent: MACHINE_ID },
    { id: SESSION_ID, kind: "session", label: shortSession(opts.sessionId), sub: "Session", parent: AGENT_ID },
  ];
  const branches: Branch[] = buildBranches(nodes, cited).filter((b) => !opts.hidden.has(b.key));
  for (const branch of branches) {
    const familyId = `family:${branch.key}`;
    out.push({
      id: familyId,
      kind: "family",
      label: branch.label,
      sub: `${branch.nodes.length.toLocaleString()} ${branch.nodes.length === 1 ? "call" : "calls"}`,
      parent: SESSION_ID,
      family: branch.family,
      familyKey: branch.key,
      count: branch.nodes.length,
      cited: branch.cited,
      flagged: branch.flagged,
    });
    const shown = opts.expanded.has(branch.key)
      ? branch.nodes
      : pickShown(branch.nodes, cited, opts.selectedId, perFamily);
    const shownIds = new Set(shown.map((n) => n.id));
    for (const node of branch.nodes) {
      if (!shownIds.has(node.id)) continue;
      out.push({
        id: node.id,
        kind: "call",
        label: shortTool(node),
        sub: node.tool.command || kindLabel(node),
        parent: familyId,
        family: branch.family,
        familyKey: branch.key,
        node,
        signal: signalOf(node, cited),
      });
    }
    const folded = branch.nodes.length - shown.length;
    if (folded > 0) {
      out.push({
        id: `more:${branch.key}`,
        kind: "more",
        label: `${folded.toLocaleString()} more`,
        sub: "Show all",
        parent: familyId,
        family: branch.family,
        familyKey: branch.key,
        count: folded,
      });
    }
  }
  return out;
}

function pickShown(nodes: SessionNode[], cited: Set<string>, selectedId: string | null, limit: number): SessionNode[] {
  const keep = new Set<string>();
  for (const n of nodes) if (isCited(n, cited) || isFlagged(n) || n.id === selectedId) keep.add(n.id);
  for (const n of nodes) {
    if (keep.size >= limit) break;
    keep.add(n.id);
  }
  return nodes.filter((n) => keep.has(n.id));
}

export function shortSession(id: string): string {
  return id.length > 20 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id;
}

// --- layout ---------------------------------------------------------------------

export interface Placed {
  entity: Entity;
  x: number;
  y: number;
}

const DEPTH: Record<EntityKind, number> = { machine: 0, agent: 1, session: 2, family: 3, call: 4, more: 4 };

/**
 * Left to right, one column per level, leaves stacked down the page and every
 * parent centred on its children. The process-tree reading order: where it
 * ran, then what ran under it.
 */
export function layoutHorizontal(entities: Entity[], colWidth = 200, rowHeight = 112): Placed[] {
  return layout(entities, (depth, slot) => ({ x: depth * colWidth, y: slot * rowHeight }));
}

/** Top to bottom, the graph's reading order: one row per level, leaves spread across. */
export function layoutVertical(entities: Entity[], colWidth = 180, rowHeight = 150): Placed[] {
  return layout(entities, (depth, slot) => ({ x: slot * colWidth, y: depth * rowHeight }));
}

function layout(entities: Entity[], place: (depth: number, slot: number) => { x: number; y: number }): Placed[] {
  const children = new Map<string, Entity[]>();
  for (const e of entities) {
    if (!e.parent) continue;
    const list = children.get(e.parent) ?? [];
    list.push(e);
    children.set(e.parent, list);
  }
  const slots = new Map<string, number>();
  let next = 0;
  // Leaves take the next slot; a parent sits at the mean of its children.
  const visit = (e: Entity): number => {
    const kids = children.get(e.id) ?? [];
    const slot = kids.length ? kids.map(visit).reduce((a, b) => a + b, 0) / kids.length : next++;
    slots.set(e.id, slot);
    return slot;
  };
  for (const root of entities.filter((e) => !e.parent)) visit(root);
  return entities.map((entity) => ({ entity, ...place(DEPTH[entity.kind], slots.get(entity.id) ?? 0) }));
}
