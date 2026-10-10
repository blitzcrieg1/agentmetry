"use client";

import React, { useMemo, useEffect } from "react";
import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  MarkerType,
  Handle,
  Position,
  NodeProps,
  Edge,
  Node
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Activity, Play, CheckCircle2, XCircle, AlertCircle, TerminalSquare } from "lucide-react";
import type { AuditEvent } from "./flight-recorder-panel";

type EventNodeData = {
  type: string;
  title: string;
  subtitle: string;
  outcome: string;
  timestamp: string;
};

const EventNode = ({ data }: NodeProps<Node<EventNodeData>>) => {
  const getOutcomeColor = (outcome: string) => {
    switch (outcome) {
      case "success": return "text-secure border-secure/30 bg-card";
      case "error": return "text-danger border-danger/40 bg-danger/[0.06]";
      case "denied": return "text-signal border-signal/40 bg-signal/[0.06]";
      default: return "text-muted-foreground border-border bg-card";
    }
  };

  const getIcon = (type: string, outcome: string) => {
    if (type === "session_start") return <Play className="w-5 h-5" />;
    if (type === "tool_called") return <TerminalSquare className="w-5 h-5" />;
    if (outcome === "success") return <CheckCircle2 className="w-5 h-5" />;
    if (outcome === "error" || outcome === "denied") return <XCircle className="w-5 h-5" />;
    return <Activity className="w-5 h-5" />;
  };

  const colors = getOutcomeColor(data.outcome);

  return (
    <div className={`px-3.5 py-3 rounded-sm border ${colors} w-64`}>
      <Handle type="target" position={Position.Left} className="!h-2 !w-2 !border-0 !bg-subtle" />
      <div className="flex items-center gap-3">
        <div className="shrink-0">{getIcon(data.type, data.outcome)}</div>
        <div className="min-w-0">
          <div className="text-sm font-bold truncate" title={data.title}>{data.title}</div>
          <div className="text-xs opacity-80 truncate" title={data.subtitle}>{data.subtitle}</div>
          <div className="text-[10px] mt-1 opacity-60 font-mono">{data.timestamp}</div>
        </div>
      </div>
      <Handle type="source" position={Position.Right} className="!h-2 !w-2 !border-0 !bg-subtle" />
    </div>
  );
};

const nodeTypes = {
  event: EventNode,
};

export function ProcessTree({ events }: { events: AuditEvent[] }) {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  useEffect(() => {
    if (!events || events.length === 0) {
      setNodes([]);
      setEdges([]);
      return;
    }

    // Sort events chronologically
    const sorted = [...events].sort((a, b) => {
      const ta = new Date(a.timestamp_utc || 0).getTime();
      const tb = new Date(b.timestamp_utc || 0).getTime();
      return ta - tb;
    });

    const newNodes: Node[] = [];
    const newEdges: Edge[] = [];

    sorted.forEach((ev, idx) => {
      const type = ev.action?.type || "unknown";
      const outcome = ev.action?.outcome || "success";
      let title = type.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase());
      let subtitle = ev.source?.app || "Agent";

      if (type === "tool_called") {
        title = ev.tool?.qualified || ev.tool?.name || "Tool Call";
        subtitle = ev.tool?.command ? `Command: ${ev.tool.command.substring(0, 30)}` : "Tool Execution";
      }

      newNodes.push({
        id: ev.event_id || `ev-${idx}`,
        type: "event",
        position: { x: idx * 350, y: 150 },
        data: {
          type,
          title,
          subtitle,
          outcome,
          timestamp: ev.timestamp_utc ? new Date(ev.timestamp_utc).toLocaleTimeString() : "",
        },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
      });

      if (idx > 0) {
        newEdges.push({
          id: `e-${sorted[idx - 1].event_id}-to-${ev.event_id}`,
          source: sorted[idx - 1].event_id || `ev-${idx - 1}`,
          target: ev.event_id || `ev-${idx}`,
          animated: true,
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: '#94a3b8',
          },
          style: { stroke: '#94a3b8', strokeWidth: 2 },
        });
      }
    });

    setNodes(newNodes);
    setEdges(newEdges);
  }, [events, setNodes, setEdges]);

  if (!events || events.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-[12px] text-subtle">
        No session selected or no events found for this session.
      </div>
    );
  }

  return (
    <div className="w-full h-full overflow-hidden rounded-sm border border-border bg-background">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.5}
        maxZoom={1.5}
      >
        <Background />
        <Controls />
        <MiniMap zoomable pannable nodeColor={(node) => {
          const outcome = (node.data as any).outcome;
          if (outcome === 'success') return '#10B981';
          if (outcome === 'error') return '#EF4444';
          if (outcome === 'denied') return '#F97316';
          return '#94A3B8';
        }} />
      </ReactFlow>
    </div>
  );
}
