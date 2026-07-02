"use client";

import { useAgentStore } from "@/lib/store";
import { useWebSocket } from "@/lib/use-websocket";
import { SkillDeck } from "@/components/skill-deck";
import { GraphVisualization } from "@/components/graph-viz/graph-visualization";
import { TelemetryPanel } from "@/components/telemetry/telemetry-panel";
import { ApprovalModal } from "@/components/approval-modal";

export function MissionControl() {
  useWebSocket();

  const terminalOutput = useAgentStore((s) => s.terminalOutput);
  const executionStatus = useAgentStore((s) => s.executionStatus);

  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center justify-between border-b border-border px-6 py-3">
        <div className="flex items-center gap-3">
          <div className="h-8 w-8 rounded bg-primary flex items-center justify-center text-primary-foreground font-bold text-sm">
            BB
          </div>
          <div>
            <h1 className="text-lg font-bold tracking-tight">BLACKBOX</h1>
            <p className="text-xs text-muted-foreground">Obsidian-Cortex Agentic OS</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={executionStatus} />
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        <aside className="w-64 border-r border-border p-4 overflow-y-auto">
          <SkillDeck />
        </aside>

        <main className="flex-1 flex flex-col p-4 gap-4 overflow-hidden">
          <div className="flex-1 min-h-0">
            <GraphVisualization />
          </div>
          <div className="h-48 rounded-lg border border-border bg-card overflow-hidden">
            <div className="flex items-center gap-2 border-b border-border px-3 py-1.5">
              <div className="h-2.5 w-2.5 rounded-full bg-red-500" />
              <div className="h-2.5 w-2.5 rounded-full bg-yellow-500" />
              <div className="h-2.5 w-2.5 rounded-full bg-green-500" />
              <span className="text-xs text-muted-foreground ml-2 font-mono">terminal</span>
            </div>
            <div className="p-3 h-[calc(100%-28px)] overflow-y-auto font-mono text-xs leading-relaxed">
              {terminalOutput.length === 0 ? (
                <span className="text-muted-foreground">
                  Ready. Select a skill from The Armory to begin.
                </span>
              ) : (
                terminalOutput.map((line, i) => (
                  <div key={i} className="text-foreground/90">
                    {line}
                  </div>
                ))
              )}
            </div>
          </div>
        </main>

        <aside className="w-64 border-l border-border p-4 overflow-y-auto">
          <TelemetryPanel />
        </aside>
      </div>

      <ApprovalModal />
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    idle: "bg-muted text-muted-foreground",
    running: "bg-blue-500/20 text-blue-400",
    waiting_for_input: "bg-amber-500/20 text-amber-400",
    completed: "bg-green-500/20 text-green-400",
    failed: "bg-red-500/20 text-red-400",
  };

  return (
    <span
      className={`rounded-full px-3 py-1 text-xs font-medium capitalize ${
        colors[status] || colors.idle
      }`}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}
