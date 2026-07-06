"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  ReactFlowProvider,
  type Node,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Archive, CircleDot, FolderOpen, Inbox, Loader2 } from "lucide-react";
import { ORCHESTRATOR_URL } from "@/lib/utils";

interface VaultEntry {
  type: "folder" | "file";
  path: string;
  name: string;
  folder?: string;
}

interface ActiveLoop {
  path: string;
  thread_id: string;
  skill: string;
  status: string;
}

const FOLDER_ACCENTS: Record<string, string> = {
  "00-Inbox": "amber",
  "10-SOPs": "violet",
  "10-Knowledge": "sky",
  "10-Products": "fuchsia",
  "20-Active-Loops": "orange",
  "30-Archive": "emerald",
  "99-Relations": "rose",
};

const ACCENT_CLASSES: Record<string, { border: string; bg: string; text: string; edge: string }> = {
  amber: {
    border: "border-amber-500/50",
    bg: "bg-amber-950/50",
    text: "text-amber-200",
    edge: "#f59e0b",
  },
  violet: {
    border: "border-violet-500/50",
    bg: "bg-violet-950/50",
    text: "text-violet-200",
    edge: "#a78bfa",
  },
  sky: {
    border: "border-sky-500/50",
    bg: "bg-sky-950/50",
    text: "text-sky-200",
    edge: "#38bdf8",
  },
  fuchsia: {
    border: "border-fuchsia-500/50",
    bg: "bg-fuchsia-950/50",
    text: "text-fuchsia-200",
    edge: "#e879f9",
  },
  orange: {
    border: "border-orange-500/50",
    bg: "bg-orange-950/50",
    text: "text-orange-200",
    edge: "#fb923c",
  },
  emerald: {
    border: "border-emerald-500/50",
    bg: "bg-emerald-950/50",
    text: "text-emerald-200",
    edge: "#34d399",
  },
  rose: {
    border: "border-rose-500/50",
    bg: "bg-rose-950/50",
    text: "text-rose-200",
    edge: "#fb7185",
  },
  slate: {
    border: "border-slate-500/40",
    bg: "bg-slate-900/60",
    text: "text-slate-300",
    edge: "#64748b",
  },
};

function accentFor(folder: string): string {
  return FOLDER_ACCENTS[folder] || "slate";
}

function ConstellationNode({
  data,
}: {
  data: {
    label: string;
    sublabel?: string;
    kind: "core" | "folder" | "file" | "loop";
    accent: string;
    pulse?: boolean;
    delay: number;
  };
}) {
  const styles = ACCENT_CLASSES[data.accent] || ACCENT_CLASSES.slate;
  const size =
    data.kind === "core" ? "min-w-[120px] px-5 py-4" : data.kind === "folder" ? "min-w-[100px] px-3 py-2.5" : "px-2 py-1.5";

  return (
    <div
      className={`rounded-xl border backdrop-blur-sm transition-shadow ${size} ${styles.border} ${styles.bg} ${
        data.pulse ? "graph-node-waiting" : data.kind !== "file" ? "animate-node-float" : ""
      }`}
      style={{ animationDelay: `${data.delay}s` }}
    >
      <div className={`flex items-center gap-2 ${data.kind === "file" ? "text-[10px]" : "text-xs"}`}>
        {data.kind === "core" ? (
          <CircleDot className={`h-4 w-4 ${styles.text}`} />
        ) : data.kind === "folder" ? (
          <FolderOpen className={`h-3.5 w-3.5 ${styles.text}`} />
        ) : data.kind === "loop" ? (
          <Loader2 className={`h-3 w-3 animate-spin ${styles.text}`} />
        ) : (
          <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: styles.edge }} />
        )}
        <span className={`font-medium ${styles.text} ${data.kind === "file" ? "max-w-[72px] truncate" : ""}`}>
          {data.label}
        </span>
      </div>
      {data.sublabel ? (
        <p className="mt-1 text-[9px] uppercase tracking-wider text-muted-foreground">{data.sublabel}</p>
      ) : null}
    </div>
  );
}

const nodeTypes = { constellation: ConstellationNode };

function buildConstellation(
  entries: VaultEntry[],
  loops: ActiveLoop[]
): { nodes: Node[]; edges: Edge[] } {
  const folders = entries.filter((e) => e.type === "folder");
  const filesByFolder = new Map<string, VaultEntry[]>();
  for (const e of entries) {
    if (e.type !== "file" || !e.folder) continue;
    const top = e.folder.split("/")[0];
    if (!filesByFolder.has(top)) filesByFolder.set(top, []);
    const list = filesByFolder.get(top)!;
    if (list.length < 4) list.push(e);
  }

  const nodes: Node[] = [
    {
      id: "vault-core",
      type: "constellation",
      position: { x: 0, y: 0 },
      data: {
        label: "Vault",
        sublabel: `${entries.filter((e) => e.type === "file").length} notes`,
        kind: "core",
        accent: "violet",
        delay: 0,
      },
    },
  ];

  const edges: Edge[] = [];
  const folderCount = Math.max(folders.length, 1);
  const folderRadius = 220;

  folders.forEach((folder, i) => {
    const angle = (i / folderCount) * Math.PI * 2 - Math.PI / 2;
    const fx = Math.cos(angle) * folderRadius;
    const fy = Math.sin(angle) * folderRadius;
    const accent = accentFor(folder.path);
    const styles = ACCENT_CLASSES[accent];
    const loopCount = loops.filter((l) => l.path.startsWith(folder.path)).length;

    nodes.push({
      id: `folder-${folder.path}`,
      type: "constellation",
      position: { x: fx - 50, y: fy - 24 },
      data: {
        label: folder.name,
        sublabel: loopCount > 0 ? `${loopCount} active` : undefined,
        kind: "folder",
        accent,
        pulse: folder.path === "20-Active-Loops" && loopCount > 0,
        delay: i * 0.35,
      },
    });

    edges.push({
      id: `core-${folder.path}`,
      source: "vault-core",
      target: `folder-${folder.path}`,
      animated: loopCount > 0,
      style: { stroke: styles.edge, strokeWidth: 1.5, opacity: 0.55 },
    });

    const satellites = filesByFolder.get(folder.path) || [];
    satellites.forEach((file, j) => {
      const satAngle = angle + ((j - (satellites.length - 1) / 2) * 0.35);
      const sr = 70;
      const sx = fx + Math.cos(satAngle) * sr;
      const sy = fy + Math.sin(satAngle) * sr;
      const fileId = `file-${file.path}`;

      nodes.push({
        id: fileId,
        type: "constellation",
        position: { x: sx - 36, y: sy - 12 },
        data: {
          label: file.name.replace(/\.md$/, ""),
          kind: "file",
          accent,
          delay: i * 0.2 + j * 0.15,
        },
      });

      edges.push({
        id: `${folder.path}-${fileId}`,
        source: `folder-${folder.path}`,
        target: fileId,
        style: { stroke: styles.edge, strokeWidth: 1, opacity: 0.25 },
      });
    });
  });

  loops.forEach((loop, i) => {
    const angle = (i / Math.max(loops.length, 1)) * Math.PI * 2;
    const lr = 110;
    const lx = Math.cos(angle) * lr;
    const ly = Math.sin(angle) * lr;
    const isWaiting = loop.status.includes("approval");

    nodes.push({
      id: `loop-${loop.thread_id || i}`,
      type: "constellation",
      position: { x: lx - 40, y: ly - 20 },
      data: {
        label: loop.skill.replace(/_/g, " "),
        sublabel: loop.status.replace(/_/g, " "),
        kind: "loop",
        accent: isWaiting ? "amber" : "orange",
        pulse: true,
        delay: i * 0.25,
      },
    });

    edges.push({
      id: `core-loop-${loop.thread_id || i}`,
      source: "vault-core",
      target: `loop-${loop.thread_id || i}`,
      animated: true,
      style: {
        stroke: isWaiting ? "#fbbf24" : "#fb923c",
        strokeWidth: 2,
        opacity: 0.7,
      },
    });
  });

  return { nodes, edges };
}

function ConstellationCanvas({ backdrop = false }: { backdrop?: boolean }) {
  const [entries, setEntries] = useState<VaultEntry[]>([]);
  const [loops, setLoops] = useState<ActiveLoop[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const [treeRes, loopsRes] = await Promise.all([
        fetch(`${ORCHESTRATOR_URL}/api/v1/vault/tree`),
        fetch(`${ORCHESTRATOR_URL}/api/v1/vault/active-loops`),
      ]);
      if (treeRes.ok) {
        const tree = await treeRes.json();
        setEntries(tree.entries || []);
      }
      if (loopsRes.ok) {
        const data = await loopsRes.json();
        setLoops(data.loops || []);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 30_000);
    return () => clearInterval(id);
  }, [load]);

  const { nodes, edges } = useMemo(
    () => buildConstellation(entries, loops),
    [entries, loops]
  );

  return (
    <div
      className={`relative h-full w-full overflow-hidden ${
        backdrop ? "" : "rounded-xl border border-border/60 bg-card/20"
      }`}
    >
      {!backdrop ? (
        <div className="absolute left-4 top-3 z-10 flex items-center gap-2 rounded-full border border-violet-500/30 bg-card/80 px-3 py-1 backdrop-blur-sm">
          <Archive className="h-3 w-3 text-violet-300" />
          <span className="text-[10px] font-medium uppercase tracking-wider text-violet-200/90">
            Memory constellation
          </span>
          {loops.length > 0 ? (
            <span className="flex items-center gap-1 text-[10px] text-amber-300">
              <Inbox className="h-3 w-3" />
              {loops.length} live
            </span>
          ) : null}
        </div>
      ) : null}

      {loading ? (
        <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          Mapping vault…
        </div>
      ) : (
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.25 }}
          proOptions={{ hideAttribution: true }}
          nodesDraggable={false}
          nodesConnectable={false}
          panOnDrag={!backdrop}
          zoomOnScroll={!backdrop}
          minZoom={0.35}
          maxZoom={1.8}
          nodesFocusable={false}
          elementsSelectable={false}
        >
          <Background variant={BackgroundVariant.Dots} color="#5b21b6" gap={24} size={1} />
          {!backdrop ? <Controls showInteractive={false} className="!bottom-3 !left-3" /> : null}
        </ReactFlow>
      )}
    </div>
  );
}

export function VaultConstellation() {
  return (
    <ReactFlowProvider>
      <ConstellationCanvas />
    </ReactFlowProvider>
  );
}

export function VaultConstellationBackdrop() {
  return (
    <div className="pointer-events-none absolute inset-0 z-0 opacity-20">
      <ReactFlowProvider>
        <ConstellationCanvas backdrop />
      </ReactFlowProvider>
    </div>
  );
}
