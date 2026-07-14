import { create } from "zustand";
import { type GraphNodeState, type NodeStatus, resolveNodeUpdates } from "@/lib/graph-utils";
import { generateSessionId } from "@/lib/utils";

export type { GraphNodeState, NodeStatus };

const SESSION_STORAGE_KEY = "agentmetry-session-id";

function initialSessionId(): string {
  // Stable across page reloads so a refresh mid-run keeps streaming events.
  if (typeof window === "undefined") return "session-ssr";
  const existing = window.localStorage.getItem(SESSION_STORAGE_KEY);
  if (existing) return existing;
  const id = generateSessionId();
  window.localStorage.setItem(SESSION_STORAGE_KEY, id);
  return id;
}

export interface TelemetryMetrics {
  inputTokens: number;
  outputTokens: number;
  cost: number;
  contextUsagePercent: number;
  latencyMs: number;
}

export interface PendingTool {
  qualified: string;
  server?: string;
  input_hash?: string;
}

export type ApprovalKind = "draft" | "tool_gate";

export interface Skill {
  id: string;
  name: string;
  display_name?: string;
  description?: string;
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
  approvalKind: ApprovalKind | null;
  pendingTool: PendingTool | null;
  lastUserInput: string;
  lastToolCalled: string | null;
  memoryHeatmap: Record<string, number>;
  wsConnected: boolean;
  runsRefreshKey: number;
  devMode: boolean;

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
  setApproval: (
    draft: string,
    confidence: number,
    meta?: {
      approvalKind?: ApprovalKind;
      pendingTool?: PendingTool | null;
    }
  ) => void;
  setLastUserInput: (input: string) => void;
  setLastToolCalled: (tool: string | null) => void;
  clearApproval: () => void;
  incrementMemoryAccess: (path: string) => void;
  setWsConnected: (connected: boolean) => void;
  bumpRunsRefresh: () => void;
  setDevMode: (enabled: boolean) => void;
  reset: (nodes?: GraphNodeState[]) => void;
  clearPipelineView: () => void;
}

export const useAgentStore = create<AgentStore>((set) => ({
  sessionId: initialSessionId(),
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
  approvalKind: null,
  pendingTool: null,
  lastUserInput: "",
  lastToolCalled: null,
  memoryHeatmap: {},
  wsConnected: false,
  runsRefreshKey: 0,
  devMode: false,

  setSkills: (skills) => set({ skills }),
  setActiveSkill: (skill) => set({ activeSkill: skill }),
  setThreadId: (id) => set({ threadId: id }),
  setExecutionStatus: (status) => set({ executionStatus: status }),
  setGraphNodes: (nodes) => set({ graphNodes: nodes }),
  updateNode: (id, status, output) =>
    set((state) => {
      const patches = resolveNodeUpdates(id, status, output);
      return {
        graphNodes: state.graphNodes.map((n) => {
          const patch = patches.find((p) => p.id === n.id);
          if (!patch) return n;
          return { ...n, status: patch.status, output: patch.output ?? n.output };
        }),
      };
    }),
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
  setApproval: (draft, confidence, meta) =>
    set({
      approvalDraft: draft,
      approvalConfidence: confidence,
      approvalKind: meta?.approvalKind ?? null,
      pendingTool: meta?.pendingTool ?? null,
    }),
  setLastUserInput: (input) => set({ lastUserInput: input }),
  setLastToolCalled: (tool) => set({ lastToolCalled: tool }),
  clearApproval: () =>
    set({
      approvalDraft: "",
      approvalConfidence: 0,
      approvalKind: null,
      pendingTool: null,
    }),
  incrementMemoryAccess: (path) =>
    set((state) => ({
      memoryHeatmap: {
        ...state.memoryHeatmap,
        [path]: (state.memoryHeatmap[path] || 0) + 1,
      },
    })),
  setWsConnected: (connected) => set({ wsConnected: connected }),
  bumpRunsRefresh: () =>
    set((state) => ({ runsRefreshKey: state.runsRefreshKey + 1 })),
  setDevMode: (enabled) => set({ devMode: enabled }),
  reset: (nodes) =>
    set((state) => {
      const base = nodes ?? state.graphNodes;
      return {
        threadId: null,
        executionStatus: "idle",
        graphNodes: base.map((n) => ({ ...n, status: "idle" as NodeStatus, output: "" })),
        terminalOutput: [],
        metrics: { inputTokens: 0, outputTokens: 0, cost: 0, contextUsagePercent: 0, latencyMs: 0 },
        approvalDraft: "",
        approvalConfidence: 0,
        approvalKind: null,
        pendingTool: null,
      };
    }),
  clearPipelineView: () => set({ graphNodes: [], executionStatus: "idle" }),
}));
