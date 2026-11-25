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
  triage: "AI Triage",
  archive: "Archive",
  research: "Research",
  analyzer: "Analyzer",
  classify_thread: "Classify",
  load_generic_sop: "Reply SOP",
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
  triage: "Sparkles",
  archive: "Archive",
  classify_thread: "GitBranch",
  load_generic_sop: "BookMarked",
};

export function buildGraphNodes(nodeIds: string[]): GraphNodeState[] {
  return nodeIds.map((id) => ({
    id,
    label: NODE_LABELS[id] ?? id.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
    status: "idle",
    output: "",
  }));
}

/** Map backend node ids → dashboard visual node ids. */
export const NODE_UPDATE_ALIASES: Record<string, string[]> = {
  finalize: ["archive"],
};

export function displayNodesForSkill(skill: { nodes?: string[]; id?: string; name?: string }): string[] {
  return nodesForSkill(skill);
}

export function resolveNodeUpdates(
  nodeId: string,
  status: NodeStatus,
  output?: string
): Array<{ id: string; status: NodeStatus; output?: string }> {
  const targets = NODE_UPDATE_ALIASES[nodeId] || [nodeId];
  return targets.map((id) => ({ id, status, output }));
}

export function nodesForSkill(skill: { nodes?: string[]; id?: string; name?: string }): string[] {
  if (skill.nodes?.length) return skill.nodes;
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
