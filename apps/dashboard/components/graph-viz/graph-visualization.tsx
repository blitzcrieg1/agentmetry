"use client";

import { useCallback, useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
  Position,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useAgentStore } from "@/lib/store";

const STATUS_COLORS: Record<string, string> = {
  idle: "#334155",
  running: "#3b82f6",
  completed: "#22c55e",
  error: "#ef4444",
  waiting: "#f59e0b",
};

function GraphNode({ data }: { data: { label: string; status: string; output: string } }) {
  const color = STATUS_COLORS[data.status] || STATUS_COLORS.idle;
  const isActive = data.status === "running" || data.status === "waiting";

  return (
    <div
      className="rounded-lg border-2 px-4 py-3 min-w-[140px] transition-all duration-300"
      style={{
        borderColor: color,
        backgroundColor: `${color}15`,
        boxShadow: isActive ? `0 0 20px ${color}40` : "none",
      }}
    >
      <div className="text-sm font-semibold text-foreground">{data.label}</div>
      <div className="text-xs text-muted-foreground mt-1 capitalize">{data.status}</div>
    </div>
  );
}

const nodeTypes = { graphNode: GraphNode };

export function GraphVisualization() {
  const graphNodes = useAgentStore((s) => s.graphNodes);
  const executionStatus = useAgentStore((s) => s.executionStatus);
  const isDimmed = executionStatus === "waiting_for_input";

  const nodes: Node[] = useMemo(
    () =>
      graphNodes.map((n, i) => ({
        id: n.id,
        type: "graphNode",
        position: { x: (i % 3) * 220, y: Math.floor(i / 3) * 120 },
        data: { label: n.label, status: n.status, output: n.output },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
      })),
    [graphNodes]
  );

  const edges: Edge[] = useMemo(() => {
    const chain = ["planner", "researcher", "writer", "critic", "human_approval", "finalize"];
    return chain.slice(0, -1).map((src, i) => ({
      id: `${src}-${chain[i + 1]}`,
      source: src,
      target: chain[i + 1],
      animated: graphNodes.find((n) => n.id === src)?.status === "running",
      style: { stroke: "#475569" },
    }));
  }, [graphNodes]);

  return (
    <div
      className={`h-full w-full rounded-lg border border-border transition-opacity duration-300 ${
        isDimmed ? "opacity-40" : ""
      }`}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        nodesConnectable={false}
        panOnDrag={false}
        zoomOnScroll={false}
      >
        <Background color="#1e293b" gap={20} />
        <Controls showInteractive={false} />
        <MiniMap
          nodeColor={(n) => STATUS_COLORS[(n.data as { status: string }).status] || "#334155"}
          maskColor="rgba(0,0,0,0.6)"
        />
      </ReactFlow>
    </div>
  );
}
