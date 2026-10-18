import { apiHeaders } from "@/lib/api";
import { ORCHESTRATOR_URL } from "@/lib/utils";

/**
 * The investigation tree for one detection: this machine, then the agent, then
 * the session, then one branch per kind of tool, then the calls.
 *
 * It is the tool-boundary analogue of an EDR process tree, and the analogy has
 * a limit worth stating wherever the tree is drawn: the hooks see the calls an
 * agent makes, not the operating system's process table. A shell call is a
 * process launch; a file read inside it is not a node. Calls are not reparented
 * under a subagent either, because parallel subagents interleave on the parent
 * session and nothing in the trail says which call was whose.
 *
 * The nodes arrive already folded server side (`core/audit/session_tree.py`):
 * an ask, its answer and its call are one node carrying all three event ids, so
 * a detection that cites the ask still lands on the call.
 */

export type Approval = "asked" | "approved" | "denied" | "inferred" | "expired" | null;

export interface SessionNode {
  id: string;
  event_ids: string[];
  kind: string;
  timestamp_utc: string;
  outcome: string;
  reason: string;
  app: string;
  adapter: string;
  tool: {
    qualified: string;
    name: string;
    server: string;
    input_hash: string;
    command?: string;
    command_truncated?: boolean;
    mitre?: { technique_id: string; technique: string; tactic_id: string; tactic: string };
  };
  approval: Approval;
  asked_as?: string;
  dlp?: { rule_id?: string; mode?: string; category?: string; severity?: string };
  tool_policy?: { rule_id?: string; action?: string; mode?: string; blocked?: boolean };
  detection?: { rule_id?: string; title?: string; severity?: string; event_ids?: string[] };
}

export interface SessionTreePayload {
  correlation_id: string;
  enabled: boolean;
  summary: {
    total?: number;
    first_utc?: string | null;
    last_utc?: string | null;
    by_type?: Record<string, number>;
    hosts?: string[];
    apps?: string[];
  };
  nodes: SessionNode[];
  truncated: boolean;
}

export type Family = "shell" | "files" | "web" | "mcp" | "subagents" | "other";

export interface Branch {
  key: string;
  label: string;
  family: Family;
  nodes: SessionNode[];
  cited: number;
  flagged: number;
}

export type Row =
  | { type: "node"; node: SessionNode; cited: boolean }
  | { type: "fold"; id: string; count: number; fromUtc: string; toUtc: string };

const SHELL = new Set(["bash", "shell", "powershell", "run", "run_command", "terminal", "exec_command", "local_shell", "run_terminal_cmd"]);
const FILES = new Set([
  "read", "write", "edit", "multiedit", "grep", "glob", "delete", "ls", "notebookedit",
  "view_file", "write_to_file", "replace_file_content", "list_dir", "grep_search",
  "read_file", "edit_file", "search_replace", "file_search", "codebase_search",
]);
const WEB = new Set(["webfetch", "websearch", "search_web", "read_url_content", "fetch", "web_search"]);

/** The tool name without the agent prefix: `cursor.Shell` → `Shell`. */
export function shortTool(node: SessionNode): string {
  const q = node.tool.qualified || node.tool.name || node.kind;
  if (q.startsWith("mcp__")) return q.split("__").slice(2).join("__") || q;
  const prefix = `${node.app}.`;
  return q.startsWith(prefix) ? q.slice(prefix.length) : q;
}

/** Which branch a node hangs from. */
export function toolFamily(node: SessionNode): { key: string; label: string; family: Family } {
  if (node.kind === "subagent_start" || node.kind === "subagent_stop") {
    return { key: "subagents", label: "Subagents", family: "subagents" };
  }
  const q = node.tool.qualified || node.tool.name;
  if (q.startsWith("mcp__")) {
    const server = q.split("__")[1] || "server";
    return { key: `mcp:${server}`, label: `MCP: ${server}`, family: "mcp" };
  }
  const short = shortTool(node);
  if (short.startsWith("MCP:") || node.app === "mcp_proxy") {
    const server = node.app === "mcp_proxy" && node.tool.server ? node.tool.server : "tools";
    return { key: `mcp:${server}`, label: server === "tools" ? "MCP tools" : `MCP: ${server}`, family: "mcp" };
  }
  const lower = short.toLowerCase();
  if (q.startsWith("shell.") || SHELL.has(lower)) return { key: "shell", label: "Shell commands", family: "shell" };
  if (FILES.has(lower)) return { key: "files", label: "Files", family: "files" };
  if (WEB.has(lower) || lower.startsWith("browser_")) return { key: "web", label: "Web", family: "web" };
  return { key: "other", label: "Other tools", family: "other" };
}

/**
 * A node someone should look at even when the detection does not cite it: a
 * refusal, or a DLP or tool policy match. A failed call is not on the list. It
 * is nearly always a command that exited non-zero, and flagging those buried
 * the two cited calls of a real session under 121 others.
 */
export function isFlagged(node: SessionNode): boolean {
  return node.kind === "denied" || Boolean(node.dlp?.rule_id) || Boolean(node.tool_policy?.rule_id);
}

export function citedSet(eventIds: string[]): Set<string> {
  return new Set(eventIds.filter(Boolean));
}

export function isCited(node: SessionNode, cited: Set<string>): boolean {
  return node.event_ids.some((id) => cited.has(id));
}

const TREE_KINDS = new Set(["call", "ask", "denied", "subagent_start", "subagent_stop"]);

/**
 * Branches for a session, the ones the detection cites first, then the
 * busiest. Lifecycle markers and detection events stay out of the branches;
 * the tree header carries those.
 */
export function buildBranches(nodes: SessionNode[], cited: Set<string>): Branch[] {
  const byKey = new Map<string, Branch>();
  for (const node of nodes) {
    if (!TREE_KINDS.has(node.kind)) continue;
    const fam = toolFamily(node);
    let branch = byKey.get(fam.key);
    if (!branch) {
      branch = { ...fam, nodes: [], cited: 0, flagged: 0 };
      byKey.set(fam.key, branch);
    }
    branch.nodes.push(node);
    if (isCited(node, cited)) branch.cited += 1;
    if (isFlagged(node)) branch.flagged += 1;
  }
  return Array.from(byKey.values()).sort(
    (a, b) => b.cited - a.cited || b.flagged - a.flagged || b.nodes.length - a.nodes.length || a.label.localeCompare(b.label),
  );
}

/**
 * What a branch shows: every cited node and every flagged one, `context`
 * neighbours either side of a cited node, and the rest folded into runs a
 * click opens. A branch nothing in it is cited by shows its flagged nodes
 * only, unless it is small enough to show whole.
 */
export function foldBranch(
  branch: Branch,
  cited: Set<string>,
  expanded: ReadonlySet<string>,
  context = 2,
  smallBranch = 3,
): Row[] {
  const { nodes } = branch;
  if (expanded.has(`${branch.key}:*`) || nodes.length <= smallBranch) {
    return nodes.map((node) => ({ type: "node", node, cited: isCited(node, cited) }));
  }
  const keep = new Array<boolean>(nodes.length).fill(false);
  nodes.forEach((node, i) => {
    if (isFlagged(node)) keep[i] = true;
    if (isCited(node, cited)) {
      for (let j = Math.max(0, i - context); j <= Math.min(nodes.length - 1, i + context); j++) keep[j] = true;
    }
  });
  const rows: Row[] = [];
  let i = 0;
  while (i < nodes.length) {
    if (keep[i]) {
      rows.push({ type: "node", node: nodes[i], cited: isCited(nodes[i], cited) });
      i += 1;
      continue;
    }
    const start = i;
    while (i < nodes.length && !keep[i]) i += 1;
    const id = `${branch.key}:${start}`;
    if (expanded.has(id)) {
      for (let j = start; j < i; j++) rows.push({ type: "node", node: nodes[j], cited: false });
    } else {
      rows.push({
        type: "fold",
        id,
        count: i - start,
        fromUtc: nodes[start].timestamp_utc,
        toUtc: nodes[i - 1].timestamp_utc,
      });
    }
  }
  return rows;
}

/** Where a moment falls in the session, 0 to 100, for the timeline strip. */
export function timelinePct(ts: string, first?: string | null, last?: string | null): number {
  const t = Date.parse(ts);
  const a = first ? Date.parse(first) : NaN;
  const b = last ? Date.parse(last) : NaN;
  if (!Number.isFinite(t) || !Number.isFinite(a) || !Number.isFinite(b) || b <= a) return 0;
  return Math.min(100, Math.max(0, ((t - a) / (b - a)) * 100));
}

/** The approval line for a node, in words an investigator reads. */
export function approvalSentence(node: SessionNode): string | null {
  switch (node.approval) {
    case "asked":
      return node.kind === "call"
        ? "The agent asked, and the call ran. No answer was recorded between the two."
        : "The agent asked to run this. No answer and no call were recorded after it.";
    case "expired":
      return "The agent asked, and the session ended before any call. The recorder closed the ask; nobody refused it.";
    case "denied":
      return "The agent asked to run this and was refused. It did not run.";
    case "inferred":
      return "The agent asked, and the call ran afterwards. Approval is inferred: no agent reports the human's click.";
    case "approved":
      return "The agent asked, and the answer was recorded as approved before the call ran.";
    default:
      return null;
  }
}

export async function fetchSessionTree(correlationId: string, aroundUtc?: string): Promise<SessionTreePayload> {
  const params = new URLSearchParams();
  if (aroundUtc) params.set("around_utc", aroundUtc);
  const qs = params.toString();
  const res = await fetch(
    `${ORCHESTRATOR_URL}/api/v1/audit/session/${encodeURIComponent(correlationId)}/tree${qs ? `?${qs}` : ""}`,
    { headers: apiHeaders(), credentials: "include" },
  );
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as SessionTreePayload;
}
