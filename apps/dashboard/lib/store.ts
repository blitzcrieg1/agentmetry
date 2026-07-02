import { create } from "zustand";
import { type GraphNodeState, type NodeStatus } from "@/lib/graph-utils";

export type { GraphNodeState, NodeStatus };

export interface TelemetryMetrics {
  inputTokens: number;
  outputTokens: number;
  cost: number;
  contextUsagePercent: number;
  latencyMs: number;
}

export interface Skill {
  id: string;
  name: string;
  display_name: string;
  description: string;
  nodes?: string[];
  default_input?: string;
}

interface AgentStore {
  sessionId: string;
  skills: Skill[];
  activeSkill: string | null;
  threadId: string | null;
  executionStatus: "idle" | "running" | "waiting_for_input" | "completed" | "failed";
  graphNodes: GraphNodeState[];
  terminalOutput: string[];
  metrics: TelemetryMetrics;
  approvalDraft: string;
  approvalConfidence: number;
  memoryHeatmap: Record<string, number>;
  wsConnected: boolean;

  setSkills: (skills: Skill[]) => void;
  setActiveSkill: (skill: string) => void;
  setThreadId: (id: string) => void;
  setExecutionStatus: (status: AgentStore["executionStatus"]) => void;
  setGraphNodes: (nodes: GraphNodeState[]) => void;
  updateNode: (id: string, status: NodeStatus, output?: string) => void;
  appendTerminal: (line: string) => void;
  appendStreamToken: (node: string, token: string) => void;
  clearTerminal: () => void;
  updateMetrics: (partial: Partial<TelemetryMetrics>) => void;
  setApproval: (draft: string, confidence: number) => void;
  clearApproval: () => void;
  incrementMemoryAccess: (path: string) => void;
  setWsConnected: (connected: boolean) => void;
  reset: (nodes?: GraphNodeState[]) => void;
}

export const useAgentStore = create<AgentStore>((set) => ({
  sessionId: `session-${Date.now()}`,
  skills: [],
  activeSkill: null,
  threadId: null,
  executionStatus: "idle",
  graphNodes: [] as GraphNodeState[],
  terminalOutput: [],
  metrics: {
    inputTokens: 0,
    outputTokens: 0,
    cost: 0,
    contextUsagePercent: 0,
    latencyMs: 0,
  },
  approvalDraft: "",
  approvalConfidence: 0,
  memoryHeatmap: {},
  wsConnected: false,

  setSkills: (skills) => set({ skills }),
  setActiveSkill: (skill) => set({ activeSkill: skill }),
  setThreadId: (id) => set({ threadId: id }),
  setExecutionStatus: (status) => set({ executionStatus: status }),
  setGraphNodes: (nodes) => set({ graphNodes: nodes }),
  updateNode: (id, status, output) =>
    set((state) => ({
      graphNodes: state.graphNodes.map((n) =>
        n.id === id ? { ...n, status, output: output ?? n.output } : n
      ),
    })),
  appendTerminal: (line) =>
    set((state) => ({ terminalOutput: [...state.terminalOutput, line] })),
  appendStreamToken: (node, token) =>
    set((state) => {
      const prefix = `[${node}] `;
      const lines = [...state.terminalOutput];
      const last = lines.length - 1;
      if (last >= 0 && lines[last].startsWith(prefix)) {
        lines[last] += token;
      } else {
        lines.push(prefix + token);
      }
      return { terminalOutput: lines };
    }),
  clearTerminal: () => set({ terminalOutput: [] }),
  updateMetrics: (partial) =>
    set((state) => ({ metrics: { ...state.metrics, ...partial } })),
  setApproval: (draft, confidence) =>
    set({ approvalDraft: draft, approvalConfidence: confidence }),
  clearApproval: () => set({ approvalDraft: "", approvalConfidence: 0 }),
  incrementMemoryAccess: (path) =>
    set((state) => ({
      memoryHeatmap: {
        ...state.memoryHeatmap,
        [path]: (state.memoryHeatmap[path] || 0) + 1,
      },
    })),
  setWsConnected: (connected) => set({ wsConnected: connected }),
  reset: (nodes) =>
    set((state) => {
      const base = nodes ?? state.graphNodes;
      return {
        threadId: null,
        executionStatus: "idle",
        graphNodes: base.map((n) => ({ ...n, status: "idle", output: "" })),
        terminalOutput: [],
        metrics: { inputTokens: 0, outputTokens: 0, cost: 0, contextUsagePercent: 0, latencyMs: 0 },
        approvalDraft: "",
        approvalConfidence: 0,
      };
    }),
}));
