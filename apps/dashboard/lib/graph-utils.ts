export type NodeStatus = "idle" | "running" | "completed" | "error" | "waiting";

export interface GraphNodeState {
  id: string;
  label: string;
  status: NodeStatus;
  output: string;
}

const NODE_LABELS: Record<string, string> = {
  planner: "Planner",
  researcher: "Researcher",
  writer: "Writer",
  critic: "Critic",
  human_approval: "Approval Gate",
  finalize: "Finalize",
  ingest: "Ingest",
  extract: "Extract",
  summarize: "Summarize",
  collect: "Collect",
  analyze: "Analyze",
  prioritize: "Prioritize",
  scan: "Inbox Scan",
  fetch: "Fetch Thread",
  draft: "Draft Reply",
  deliver: "File Draft",
  inbox_fetch: "Fetch Inbox",
  triage: "AI Triage",
  archive: "Archive",
  research: "Research",
  analyzer: "Analyzer",
  classify_thread: "Classify",
  load_client_sop: "Client SOP",
  load_generic_sop: "Reply SOP",
  escalate_draft: "Escalate",
  replan_fetch: "Re-fetch",
};

/** Lucide icon names passed to GraphNode */
export const NODE_ICONS: Record<string, string> = {
  planner: "Map",
  researcher: "Search",
  writer: "PenLine",
  critic: "ShieldCheck",
  human_approval: "UserCheck",
  finalize: "Archive",
  ingest: "Download",
  extract: "FileSearch",
  summarize: "FileText",
  collect: "FolderOpen",
  analyze: "BarChart3",
  prioritize: "ListOrdered",
  scan: "Mail",
  fetch: "MailOpen",
  draft: "PenLine",
  deliver: "Send",
  inbox_fetch: "Mail",
  triage: "Sparkles",
  archive: "Archive",
  classify_thread: "GitBranch",
  load_client_sop: "BookOpen",
  load_generic_sop: "BookMarked",
  escalate_draft: "AlertTriangle",
  replan_fetch: "RefreshCw",
};

export function buildGraphNodes(nodeIds: string[]): GraphNodeState[] {
  return nodeIds.map((id) => ({
    id,
    label: NODE_LABELS[id] ?? id.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
    status: "idle",
    output: "",
  }));
}

export function defaultInputForSkill(skill: { id?: string; name?: string; default_input?: string }): string {
  if (skill.default_input) return skill.default_input;
  const id = skill.id || skill.name || "";
  if (id === "lead_gen") return "Generate outreach for AI infrastructure prospects from vault context";
  if (id === "summarize_meeting") return "Summarize the latest meeting notes from the inbox and extract action items";
  if (id === "weekly_review") return "Review this week's vault activity and produce a prioritized plan for next week";
  if (id === "gmail_inbox_brief") return "morning inbox brief";
  if (id === "customer_reply") return "00-Inbox/sample-shipping-complaint.md";
  if (id === "sop_drift_review") return "20";
  return "Describe what the agent should do...";
}

/** Richer visual pipelines than raw YAML node lists (display only). */
const VISUAL_PIPELINES: Record<string, string[]> = {
  gmail_inbox_brief: ["inbox_fetch", "triage", "archive"],
};

/** Map backend node ids → dashboard visual node ids. */
export const NODE_UPDATE_ALIASES: Record<string, string[]> = {
  scan: ["inbox_fetch", "triage"],
  finalize: ["archive"],
};

export function displayNodesForSkill(skill: { nodes?: string[]; id?: string; name?: string }): string[] {
  const id = skill.id || skill.name || "";
  if (VISUAL_PIPELINES[id]) return VISUAL_PIPELINES[id];
  return nodesForSkill(skill);
}

export function resolveNodeUpdates(
  nodeId: string,
  status: NodeStatus,
  output?: string
): Array<{ id: string; status: NodeStatus; output?: string }> {
  const targets = NODE_UPDATE_ALIASES[nodeId] || [nodeId];
  if (nodeId === "scan" && status === "running") {
    return [
      { id: "inbox_fetch", status: "running", output },
      { id: "triage", status: "running" },
    ];
  }
  if (nodeId === "scan" && status === "completed") {
    return [
      { id: "inbox_fetch", status: "completed", output: "Inbox loaded" },
      { id: "triage", status: "completed", output },
    ];
  }
  return targets.map((id) => ({ id, status, output }));
}

export function nodesForSkill(skill: { nodes?: string[]; id?: string; name?: string }): string[] {
  if (skill.nodes?.length) return skill.nodes;
  const id = skill.id || skill.name || "";
  if (id === "lead_gen") return ["planner", "researcher", "writer", "critic", "human_approval", "finalize"];
  if (id === "summarize_meeting") return ["ingest", "extract", "summarize", "finalize"];
  if (id === "weekly_review") return ["collect", "analyze", "prioritize", "finalize"];
  return [];
}

/** Left-to-right pipeline positions, centered vertically */
export function layoutPipelineNodes(count: number): { x: number; y: number }[] {
  const spacing = count <= 3 ? 320 : count <= 5 ? 240 : 200;
  const y = 40;
  const totalWidth = (count - 1) * spacing;
  const startX = -totalWidth / 2;
  return Array.from({ length: count }, (_, i) => ({
    x: startX + i * spacing,
    y,
  }));
}
