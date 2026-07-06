"use client";

import { useEffect, useMemo } from "react";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlowProvider,
  useReactFlow,
  type Node,
  type Edge,
  Position,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  AlertTriangle,
  Archive,
  BarChart3,
  BookMarked,
  BookOpen,
  Download,
  FileSearch,
  FileText,
  FolderOpen,
  GitBranch,
  Inbox,
  ListOrdered,
  Mail,
  MailOpen,
  Map,
  PenLine,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  UserCheck,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { useAgentStore } from "@/lib/store";
import { NODE_ICONS, layoutPipelineNodes, type NodeStatus } from "@/lib/graph-utils";
import { VaultConstellation, VaultConstellationBackdrop } from "@/components/graph-viz/vault-constellation";

const ICON_MAP: Record<string, LucideIcon> = {
  Map,
  Search,
  PenLine,
  ShieldCheck,
  UserCheck,
  Archive,
  Download,
  FileSearch,
  FileText,
  FolderOpen,
  BarChart3,
  ListOrdered,
  Inbox,
  Mail,
  MailOpen,
  Send,
  GitBranch,
  BookOpen,
  BookMarked,
  AlertTriangle,
  RefreshCw,
  Sparkles,
  Zap,
};

const STATUS_STYLES: Record<
  NodeStatus,
  { border: string; bg: string; dot: string; edge: string }
> = {
  idle: {
    border: "border-slate-600/60",
    bg: "bg-slate-900/80",
    dot: "bg-slate-500",
    edge: "#475569",
  },
  running: {
    border: "border-violet-400/90",
    bg: "bg-violet-950/70",
    dot: "bg-violet-400",
    edge: "#a78bfa",
  },
  completed: {
    border: "border-emerald-500/80",
    bg: "bg-emerald-950/50",
    dot: "bg-emerald-400",
    edge: "#34d399",
  },
  error: {
    border: "border-red-500/70",
    bg: "bg-red-950/40",
    dot: "bg-red-400",
    edge: "#f87171",
  },
  waiting: {
    border: "border-amber-400/80",
    bg: "bg-amber-950/40",
    dot: "bg-amber-400",
    edge: "#fbbf24",
  },
};

function GraphNode({
  data,
}: {
  data: {
    label: string;
    status: NodeStatus;
    output: string;
    nodeId: string;
  };
}) {
  const styles = STATUS_STYLES[data.status] || STATUS_STYLES.idle;
  const isActive = data.status === "running" || data.status === "waiting";
  const iconName = NODE_ICONS[data.nodeId] || "Zap";
  const Icon = ICON_MAP[iconName] || Zap;

  return (
    <div
      className={`relative min-w-[180px] rounded-xl border-2 px-4 py-3.5 shadow-lg backdrop-blur-md transition-all duration-500 ${styles.border} ${styles.bg} ${
        data.status === "running"
          ? "graph-node-running scale-105"
          : data.status === "waiting"
            ? "graph-node-waiting scale-105"
            : ""
      }`}
    >
      <div className="flex items-start gap-2.5">
        <div
          className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border ${styles.border} ${styles.bg}`}
        >
          <Icon className={`h-4 w-4 ${isActive ? "text-violet-100" : "text-violet-200/90"}`} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold leading-tight text-foreground">{data.label}</div>
          <div className="mt-1 flex items-center gap-1.5">
            <span className={`h-2 w-2 rounded-full ${styles.dot} ${isActive ? "animate-pulse" : ""}`} />
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground capitalize">
              {data.status}
            </span>
          </div>
        </div>
      </div>
      {data.output ? (
        <p className="mt-2 line-clamp-2 border-t border-border/40 pt-2 text-[10px] leading-relaxed text-muted-foreground">
          {data.output.slice(0, 120)}
          {data.output.length > 120 ? "…" : ""}
        </p>
      ) : null}
    </div>
  );
}

const nodeTypes = { graphNode: GraphNode };

function FitViewOnChange({ count, status }: { count: number; status: string }) {
  const { fitView } = useReactFlow();
  useEffect(() => {
    if (count > 0) {
      const t = setTimeout(
        () => fitView({ padding: count <= 3 ? 0.55 : 0.35, duration: 500, maxZoom: 1.2 }),
        80
      );
      return () => clearTimeout(t);
    }
  }, [count, status, fitView]);
  return null;
}

function GraphCanvas() {
  const graphNodes = useAgentStore((s) => s.graphNodes);
  const executionStatus = useAgentStore((s) => s.executionStatus);
  const activeSkill = useAgentStore((s) => s.activeSkill);
  const isDimmed = executionStatus === "waiting_for_input";
  const hasPipeline = graphNodes.length > 0;
  const anyRunning = graphNodes.some((n) => n.status === "running") || executionStatus === "running";

  const positions = useMemo(() => layoutPipelineNodes(graphNodes.length), [graphNodes.length]);

  const nodes: Node[] = useMemo(
    () =>
      graphNodes.map((n, i) => ({
        id: n.id,
        type: "graphNode",
        position: positions[i] ?? { x: i * 320, y: 40 },
        data: { label: n.label, status: n.status, output: n.output, nodeId: n.id },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
      })),
    [graphNodes, positions]
  );

  const edges: Edge[] = useMemo(() => {
    const ids = graphNodes.map((n) => n.id);
    return ids.slice(0, -1).map((src, i) => {
      const srcNode = graphNodes.find((n) => n.id === src);
      const tgtNode = graphNodes.find((n) => n.id === ids[i + 1]);
      const styles = STATUS_STYLES[srcNode?.status ?? "idle"];
      const flow =
        srcNode?.status === "running" ||
        tgtNode?.status === "running" ||
        (anyRunning && srcNode?.status === "completed" && tgtNode?.status !== "completed");
      return {
        id: `${src}-${ids[i + 1]}`,
        source: src,
        target: ids[i + 1],
        animated: flow,
        style: {
          stroke: flow ? styles.edge : "#475569",
          strokeWidth: flow ? 3 : 1.5,
          opacity: flow ? 1 : 0.5,
        },
      };
    });
  }, [graphNodes, anyRunning]);

  if (!hasPipeline) {
    return <VaultConstellation />;
  }

  return (
    <div className="relative h-full w-full overflow-hidden rounded-xl border border-border/60">
      <VaultConstellationBackdrop />
      <div
        className={`relative z-10 h-full w-full transition-opacity duration-500 ${
          isDimmed ? "opacity-60" : ""
        }`}
      >
        {activeSkill ? (
          <div className="absolute left-4 top-3 z-20 rounded-full border border-violet-500/40 bg-card/90 px-3 py-1 text-[10px] font-medium uppercase tracking-wider text-violet-200 backdrop-blur-sm">
            {activeSkill.replace(/_/g, " ")}
          </div>
        ) : null}
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.55, maxZoom: 1.2 }}
          proOptions={{ hideAttribution: true }}
          nodesDraggable={false}
          nodesConnectable={false}
          panOnDrag
          zoomOnScroll
          minZoom={0.5}
          maxZoom={1.4}
          className="!bg-transparent"
        >
          <FitViewOnChange count={graphNodes.length} status={executionStatus} />
          <Background variant={BackgroundVariant.Dots} color="#7c3aed" gap={18} size={1} />
          <Controls showInteractive={false} className="!bottom-3 !left-3" />
          <MiniMap
            className="!bottom-3 !right-3"
            nodeColor={(n) => {
              const st = (n.data as { status: NodeStatus }).status;
              return STATUS_STYLES[st]?.edge ?? "#475569";
            }}
            maskColor="rgba(8, 6, 18, 0.75)"
          />
        </ReactFlow>
      </div>
    </div>
  );
}

export function GraphVisualization() {
  return (
    <ReactFlowProvider>
      <GraphCanvas />
    </ReactFlowProvider>
  );
}
