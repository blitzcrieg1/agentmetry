"use client";

import { useEffect, useRef } from "react";
import {
  CheckCircle2,
  Code2,
  Loader2,
  Radio,
  Shield,
  Wifi,
  WifiOff,
} from "lucide-react";
import { useAgentStore } from "@/lib/store";
import { useWebSocket } from "@/lib/use-websocket";
import { SkillDeck } from "@/components/skill-deck";
import { GraphVisualization } from "@/components/graph-viz/graph-visualization";
import { TelemetryPanel } from "@/components/telemetry/telemetry-panel";
import { ApprovalInboxCard } from "@/components/approval-inbox-card";
import { FlightRecorderPanel } from "@/components/flight-recorder-panel";
import { AuditFreshnessBadge } from "@/components/audit-freshness-badge";

function terminalLineClass(line: string): string {
  if (line.startsWith("✗") || line.toLowerCase().includes("error") || line.startsWith("Error:")) {
    return "text-red-400/90";
  }
  if (line.startsWith("✓") || line.includes("completed") || line.includes("approved")) {
    return "text-emerald-400/90";
  }
  if (line.startsWith("✨")) return "text-violet-100 drop-shadow-[0_0_6px_rgba(167,139,250,0.6)]";
  if (line.startsWith("⚠")) return "text-amber-400/90";
  if (line.startsWith("▶") || line.startsWith("Launching")) return "text-violet-300/90";
  if (line.startsWith("Task:")) return "text-muted-foreground";
  return "text-foreground/85";
}

function RunningState({ skill }: { skill: string | null }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-violet-500/20 bg-violet-950/20 px-5 py-4">
      <Loader2 className="h-5 w-5 animate-spin text-violet-400" />
      <div>
        <p className="text-sm font-medium text-violet-200">Run in progress</p>
        <p className="text-xs text-zinc-500 capitalize">
          {(skill || "skill").replace(/_/g, " ")} is running…
        </p>
      </div>
    </div>
  );
}

function CompletedBanner() {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-emerald-500/20 bg-emerald-950/20 px-5 py-4">
      <CheckCircle2 className="h-5 w-5 text-emerald-400" />
      <p className="text-sm text-emerald-200">Run approved — recorded to the audit trail</p>
    </div>
  );
}

export function MissionControl() {
  useWebSocket();

  const terminalOutput = useAgentStore((s) => s.terminalOutput);
  const executionStatus = useAgentStore((s) => s.executionStatus);
  const wsConnected = useAgentStore((s) => s.wsConnected);
  const activeSkill = useAgentStore((s) => s.activeSkill);
  const devMode = useAgentStore((s) => s.devMode);
  const setDevMode = useAgentStore((s) => s.setDevMode);
  const terminalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = terminalRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [terminalOutput]);

  return (
    <div className="flex h-screen flex-col">
      <header className="glass-panel relative z-20 flex items-center justify-between border-b border-zinc-800/60 px-6 py-3">
        <div className="flex items-center gap-3">
          <div className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-violet-500/15 ring-1 ring-violet-500/30 shadow-lg shadow-violet-900/30">
            <Shield className="h-5 w-5 text-violet-300" />
            {executionStatus === "running" ? (
              <span className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 animate-pulse rounded-full bg-emerald-400 ring-2 ring-background" />
            ) : null}
          </div>
          <div>
            <h1 className="text-gradient text-lg font-bold tracking-tight">AgentAudit</h1>
            <p className="text-xs text-muted-foreground">Flight recorder for governed agents</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <AuditFreshnessBadge />
          <DevModeToggle enabled={devMode} onChange={setDevMode} />
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
        <aside className="glass-panel w-72 shrink-0 overflow-y-auto border-r border-zinc-800/60 p-4">
          <SkillDeck />
        </aside>

        <main className="flex flex-1 flex-col gap-4 overflow-hidden p-5">
          {devMode ? (
            <>
              {executionStatus === "waiting_for_input" ? (
                <div className="shrink-0">
                  <ApprovalInboxCard />
                </div>
              ) : null}
              <div className="min-h-0 flex-1">
                <GraphVisualization />
              </div>
              <div className="glass-panel h-52 shrink-0 overflow-hidden rounded-xl border-zinc-800/60">
                <div className="flex items-center gap-2 border-b border-zinc-800/60 bg-zinc-950/50 px-3 py-2">
                  <div className="h-2.5 w-2.5 rounded-full bg-red-500/80" />
                  <div className="h-2.5 w-2.5 rounded-full bg-yellow-500/80" />
                  <div className="h-2.5 w-2.5 rounded-full bg-green-500/80" />
                  <span className="ml-2 font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                    agent terminal
                  </span>
                </div>
                <div
                  ref={terminalRef}
                  className="h-[calc(100%-36px)] overflow-y-auto bg-zinc-950/50 p-3 font-mono text-xs leading-relaxed"
                >
                  {terminalOutput.length === 0 ? (
                    <span className="text-muted-foreground/70">
                      Ready. Select a skill to begin.
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
            </>
          ) : (
            <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
              {executionStatus === "waiting_for_input" ? (
                <div className="shrink-0">
                  <ApprovalInboxCard />
                </div>
              ) : executionStatus === "running" ? (
                <div className="shrink-0">
                  <RunningState skill={activeSkill} />
                </div>
              ) : executionStatus === "completed" ? (
                <div className="shrink-0">
                  <CompletedBanner />
                </div>
              ) : null}

              <FlightRecorderPanel />
            </div>
          )}
        </main>

        <aside className="glass-panel w-72 shrink-0 overflow-y-auto border-l border-zinc-800/60 p-4">
          <TelemetryPanel />
        </aside>
      </div>
    </div>
  );
}

function DevModeToggle({
  enabled,
  onChange,
}: {
  enabled: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!enabled)}
      className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-medium uppercase tracking-wider transition-colors ${
        enabled
          ? "border-violet-500/40 bg-violet-950/50 text-violet-300"
          : "border-zinc-700/60 bg-zinc-950/40 text-zinc-500 hover:text-zinc-300"
      }`}
      title="Show LangGraph pipeline and raw terminal"
    >
      <Code2 className="h-3 w-3" />
      Dev
    </button>
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
