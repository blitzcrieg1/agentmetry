"use client";

import { useEffect, useMemo } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  type Edge,
  type Node,
  type NodeProps,
  Position,
  ReactFlow,
  useNodesState,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useTheme } from "next-themes";
import { Ban, Monitor, Plus, ShieldAlert, TerminalSquare } from "lucide-react";
import { AgentMark } from "@/components/ui/agent-mark";
import { FAMILY_ICON } from "@/components/investigation/family-icon";
import type { Entity, Placed } from "@/lib/investigation";

export type Orientation = "horizontal" | "vertical";

type EntityData = {
  entity: Entity;
  app: string;
  orientation: Orientation;
  selected: boolean;
  dimmed: boolean;
};

const SIGNAL_RING: Record<string, string> = {
  cited: "border-danger bg-danger/15 text-danger",
  refused: "border-caution bg-caution/15 text-caution",
  dlp: "border-caution bg-caution/15 text-caution",
  policy: "border-caution bg-caution/15 text-caution",
  error: "border-danger/60 bg-card text-danger",
};

/**
 * One entity on the canvas: a marker with its name underneath, the way an EDR
 * draws a process. The handles sit on the marker, not the label, so edges meet
 * the circle rather than the middle of the text.
 */
function EntityNode({ data }: NodeProps<Node<EntityData>>) {
  const { entity, app, orientation, selected, dimmed } = data;
  const horizontal = orientation === "horizontal";
  const isCall = entity.kind === "call";
  const signal = entity.signal ?? null;
  const size = entity.kind === "call" ? (signal ? "h-9 w-9" : "h-6 w-6") : "h-10 w-10";
  const ring = isCall
    ? signal
      ? SIGNAL_RING[signal]
      : "border-border bg-muted text-muted-foreground"
    : entity.kind === "more"
      ? "border-dashed border-border bg-card text-muted-foreground"
      : "border-border bg-card text-foreground";
  const Icon =
    entity.kind === "machine"
      ? Monitor
      : entity.kind === "session"
        ? TerminalSquare
        : entity.kind === "more"
          ? Plus
          : entity.family
            ? FAMILY_ICON[entity.family]
            : TerminalSquare;

  return (
    <div className={`flex w-[150px] flex-col items-center text-center transition-opacity ${dimmed ? "opacity-30" : ""}`}>
      {entity.kind === "family" && (entity.cited || entity.flagged) ? (
        <div className="mb-1 flex h-4 items-center gap-1">
          {entity.cited ? <span className="rounded-sm bg-danger/15 px-1 font-mono text-[11px] leading-4 text-danger">{entity.cited} cited</span> : null}
          {entity.flagged ? <span className="rounded-sm bg-caution/15 px-1 font-mono text-[11px] leading-4 text-caution">{entity.flagged} flagged</span> : null}
        </div>
      ) : (
        <div className="mb-1 h-4" />
      )}
      <div
        className={`relative grid shrink-0 place-items-center rounded-full border-2 shadow-sm ${size} ${ring} ${
          selected ? "ring-4 ring-signal/40" : ""
        }`}
      >
        <Handle type="target" position={horizontal ? Position.Left : Position.Top} className="!h-1 !w-1 !min-w-0 !border-0 !bg-transparent" />
        {entity.kind === "agent" ? (
          <AgentMark app={app} size="sm" />
        ) : isCall ? (
          signal === "cited" ? (
            <ShieldAlert className="h-4 w-4" aria-hidden />
          ) : signal === "refused" ? (
            <Ban className="h-4 w-4" aria-hidden />
          ) : signal ? (
            <ShieldAlert className="h-4 w-4" aria-hidden />
          ) : null
        ) : (
          <Icon className="h-4 w-4" aria-hidden />
        )}
        <Handle type="source" position={horizontal ? Position.Right : Position.Bottom} className="!h-1 !w-1 !min-w-0 !border-0 !bg-transparent" />
      </div>
      <p className={`mt-1.5 max-w-full truncate text-[12px] ${isCall ? "font-mono" : "font-medium"} ${selected ? "text-foreground" : "text-foreground/90"}`} title={entity.label}>
        {entity.label}
      </p>
      {entity.sub ? (
        <p className="max-w-full truncate font-mono text-[12px] text-subtle" title={entity.sub}>
          {entity.sub}
        </p>
      ) : null}
    </div>
  );
}

const NODE_TYPES = { entity: EntityNode };

/**
 * The tree and the graph are the same hierarchy on one canvas, laid out two
 * ways: left to right and locked for the tree, top to bottom and draggable for
 * the graph. Clicking a call selects it, clicking "more" opens its category,
 * clicking anything else shows its summary.
 */
export function ActivityCanvas({
  placed,
  app,
  orientation,
  selectedId,
  isDimmed,
  onSelect,
  onExpand,
  layoutKey,
}: {
  placed: Placed[];
  app: string;
  orientation: Orientation;
  selectedId: string | null;
  isDimmed: (entity: Entity) => boolean;
  onSelect: (entity: Entity) => void;
  onExpand: (familyKey: string) => void;
  layoutKey: string;
}) {
  const { resolvedTheme } = useTheme();
  const graph = orientation === "vertical";

  const initialNodes = useMemo<Node<EntityData>[]>(
    () =>
      placed.map(({ entity, x, y }) => ({
        id: entity.id,
        type: "entity",
        position: { x, y },
        draggable: graph,
        selectable: false,
        data: { entity, app, orientation, selected: entity.id === selectedId, dimmed: isDimmed(entity) },
      })),
    [placed, app, orientation, selectedId, isDimmed, graph],
  );
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);

  // Keep positions the analyst dragged to; refresh selection and dimming only.
  useEffect(() => {
    setNodes((current) => {
      const at = new Map(current.map((n) => [n.id, n.position]));
      return initialNodes.map((n) => ({ ...n, position: graph ? at.get(n.id) ?? n.position : n.position }));
    });
  }, [initialNodes, setNodes, graph]);

  const edges = useMemo<Edge[]>(
    () =>
      placed
        .filter(({ entity }) => entity.parent)
        .map(({ entity }) => {
          const hot = entity.signal === "cited";
          return {
            id: `${entity.parent}->${entity.id}`,
            source: entity.parent!,
            target: entity.id,
            type: graph ? "straight" : "smoothstep",
            animated: false,
            style: {
              stroke: hot ? "hsl(var(--danger))" : "hsl(var(--border))",
              strokeWidth: hot ? 2 : 1.25,
              opacity: isDimmed(entity) ? 0.3 : 1,
            },
          };
        }),
    [placed, graph, isDimmed],
  );

  return (
    <div className="relative min-h-[28rem] flex-1">
      <ReactFlow
        key={layoutKey}
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        onNodesChange={onNodesChange}
        onNodeClick={(_, node) => {
          const entity = (node.data as EntityData).entity;
          if (entity.kind === "more" && entity.familyKey) onExpand(entity.familyKey);
          else onSelect(entity);
        }}
        nodesConnectable={false}
        nodesDraggable={graph}
        fitView
        fitViewOptions={{ padding: 0.2, maxZoom: 1.1 }}
        minZoom={0.2}
        maxZoom={2}
        colorMode={resolvedTheme === "dark" ? "dark" : "light"}
        className="!bg-transparent"
      >
        <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="hsl(var(--border))" />
        <Controls showInteractive={false} position="bottom-left" />
      </ReactFlow>
    </div>
  );
}
