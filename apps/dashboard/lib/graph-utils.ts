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
};

export function buildGraphNodes(nodeIds: string[]): GraphNodeState[] {
  return nodeIds.map((id) => ({
    id,
    label: NODE_LABELS[id] ?? id.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
    status: "idle",
    output: "",
  }));
}

export const LEAD_GEN_NODES = buildGraphNodes([
  "planner",
  "researcher",
  "writer",
  "critic",
  "human_approval",
  "finalize",
]);

export const SKILL_DEFAULTS: Record<string, { input: string; nodes: string[] }> = {
  lead_gen: {
    input: "Generate outreach for AI infrastructure prospects from vault context",
    nodes: ["planner", "researcher", "writer", "critic", "human_approval", "finalize"],
  },
  summarize_meeting: {
    input: "Summarize the latest meeting notes from the inbox and extract action items",
    nodes: ["ingest", "extract", "summarize", "finalize"],
  },
};
