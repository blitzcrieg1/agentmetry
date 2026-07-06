"use client";

import { useEffect, useRef } from "react";
import { Radio, Wifi, WifiOff } from "lucide-react";
import { useAgentStore } from "@/lib/store";
import { useWebSocket } from "@/lib/use-websocket";
import { SkillDeck } from "@/components/skill-deck";
import { GraphVisualization } from "@/components/graph-viz/graph-visualization";
import { TelemetryPanel } from "@/components/telemetry/telemetry-panel";
import { ApprovalModal } from "@/components/approval-modal";

function terminalLineClass(line: string): string {
  if (line.startsWith("✗") || line.toLowerCase().includes("error") || line.startsWith("Error:")) {
    return "text-red-400/90";
  }
  if (line.startsWith("✓") || line.includes("completed") || line.includes("approved")) {
    return "text-emerald-400/90";
  }
  if (line.startsWith("⚠")) return "text-amber-400/90";
  if (line.startsWith("▶") || line.startsWith("Launching")) return "text-violet-300/90";
  if (line.startsWith("Task:")) return "text-muted-foreground";
  return "text-foreground/85";
}

export function MissionControl() {
  useWebSocket();

  const terminalOutput = useAgentStore((s) => s.terminalOutput);
  const executionStatus = useAgentStore((s) => s.executionStatus);
  const wsConnected = useAgentStore((s) => s.wsConnected);
  const activeSkill = useAgentStore((s) => s.activeSkill);
  const terminalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = terminalRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [terminalOutput]);

  return (
    <div className="flex h-screen flex-col">
      <header className="glass-panel relative z-20 flex items-center justify-between border-b px-6 py-3">
        <div className="flex items-center gap-3">
          <div className="relative h-10 w-10 shrink-0 overflow-hidden rounded-lg ring-1 ring-violet-500/30 shadow-lg shadow-violet-900/30">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src="/blackbox-logo.png"
              alt="BLACKBOX"
              className="h-full w-full object-cover"
            />
            {executionStatus === "running" ? (
              <span className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 animate-pulse rounded-full bg-emerald-400 ring-2 ring-background" />
            ) : null}
          </div>
          <div>
            <h1 className="text-gradient text-lg font-bold tracking-tight">BLACKBOX</h1>
            <p className="text-xs text-muted-foreground">Obsidian-Cortex Agentic OS</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <ConnectionPill connected={wsConnected} />
          {activeSkill && executionStatus !== "idle" ? (
            <span className="hidden text-xs text-muted-foreground sm:inline">
              <Radio className="mr-1 inline h-3 w-3 text-violet-400" />
              {activeSkill.replace(/_/g, " ")}
            </span>
          ) : null}
          <StatusBadge status={executionStatus} />
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        <aside className="glass-panel w-72 shrink-0 overflow-y-auto border-r p-4">
          <SkillDeck />
        </aside>

        <main className="flex flex-1 flex-col gap-4 overflow-hidden p-4">
          <div className="min-h-0 flex-1">
            <GraphVisualization />
          </div>
          <div className="glass-panel h-52 shrink-0 overflow-hidden rounded-xl">
            <div className="flex items-center gap-2 border-b border-border/60 bg-black/30 px-3 py-2">
              <div className="h-2.5 w-2.5 rounded-full bg-red-500/80" />
              <div className="h-2.5 w-2.5 rounded-full bg-yellow-500/80" />
              <div className="h-2.5 w-2.5 rounded-full bg-green-500/80" />
              <span className="ml-2 font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                agent terminal
              </span>
            </div>
            <div
              ref={terminalRef}
              className="h-[calc(100%-36px)] overflow-y-auto bg-black/40 p-3 font-mono text-xs leading-relaxed"
            >
              {terminalOutput.length === 0 ? (
                <span className="text-muted-foreground/70">
                  Ready. Select a skill from The Armory to begin.
                </span>
              ) : (
                terminalOutput.map((line, i) => (
                  <div
                    key={i}
                    className={`animate-fade-in-up ${terminalLineClass(line)}`}
                    style={{ animationDelay: `${Math.min(i * 20, 200)}ms` }}
                  >
                    {line}
                  </div>
                ))
              )}
            </div>
          </div>
        </main>

        <aside className="glass-panel w-72 shrink-0 overflow-y-auto border-l p-4">
          <TelemetryPanel />
        </aside>
      </div>

      <ApprovalModal />
    </div>
  );
}

function ConnectionPill({ connected }: { connected: boolean }) {
  return (
    <span
      className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-medium uppercase tracking-wider ${
        connected
          ? "border-emerald-500/30 bg-emerald-950/40 text-emerald-400"
          : "border-red-500/30 bg-red-950/30 text-red-400"
      }`}
    >
      {connected ? <Wifi className="h-3 w-3" /> : <WifiOff className="h-3 w-3" />}
      {connected ? "Live" : "Offline"}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    idle: "bg-muted/80 text-muted-foreground border-border",
    running: "bg-violet-500/20 text-violet-300 border-violet-500/40 animate-pulse",
    waiting_for_input: "bg-amber-500/20 text-amber-300 border-amber-500/40",
    completed: "bg-emerald-500/20 text-emerald-300 border-emerald-500/40",
    failed: "bg-red-500/20 text-red-300 border-red-500/40",
  };

  return (
    <span
      className={`rounded-full border px-3 py-1 text-xs font-medium capitalize ${
        colors[status] || colors.idle
      }`}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}
