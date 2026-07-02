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
  return "Describe what the agent should do...";
}

export function nodesForSkill(skill: { nodes?: string[]; id?: string; name?: string }): string[] {
  if (skill.nodes?.length) return skill.nodes;
  const id = skill.id || skill.name || "";
  if (id === "lead_gen") return ["planner", "researcher", "writer", "critic", "human_approval", "finalize"];
  if (id === "summarize_meeting") return ["ingest", "extract", "summarize", "finalize"];
  if (id === "weekly_review") return ["collect", "analyze", "prioritize", "finalize"];
  return [];
}
