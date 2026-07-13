"use client";

import { useState } from "react";
import Image from "next/image";
import {
  Wifi,
  WifiOff,
} from "lucide-react";
import { useAgentStore } from "@/lib/store";
import { useWebSocket } from "@/lib/use-websocket";
import { FlightRecorderPanel } from "@/components/flight-recorder-panel";
import { AnalyticsPanel } from "@/components/analytics-panel";
import { AuditFreshnessBadge } from "@/components/audit-freshness-badge";
import { ThemeToggle } from "@/components/theme-toggle";
import { ORCHESTRATOR_URL } from "@/lib/utils";

export function MissionControl() {
  useWebSocket();

  const [activeTab, setActiveTab] = useState<"recorder" | "analytics">("recorder");

  const wsConnected = useAgentStore((s) => s.wsConnected);

  return (
    <div className="flex h-screen flex-col">
      <header className="glass-panel relative z-20 flex items-center justify-between border-b border-slate-300 dark:border-slate-800/60 px-6 py-3">
        <div className="flex items-center gap-3">
          <div className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-slate-100 dark:bg-slate-900/80 ring-1 ring-slate-700/60">
            <Image
              src="/agentmetry-icon-white.svg"
              alt="Agentmetry"
              width={28}
              height={28}
              priority
              className="invert dark:invert-0"
            />
          </div>
          <div>
            <h1 className="text-gradient text-xl font-bold tracking-tight">Agentmetry</h1>
            <p className="text-sm text-slate-500">SIEM flight recorder for AI agents</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <ThemeToggle />
          <div className="flex rounded-md border border-slate-300 dark:border-slate-800 p-1 bg-slate-100 dark:bg-slate-900/50">
            <button
              onClick={() => setActiveTab("recorder")}
              className={`px-3 py-1 text-sm rounded-sm transition-colors ${
                activeTab === "recorder" ? "bg-emerald-500/20 text-emerald-700 dark:text-emerald-300" : "text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:text-slate-300"
              }`}
            >
              Flight Recorder
            </button>
            <button
              onClick={() => setActiveTab("analytics")}
              className={`px-3 py-1 text-sm rounded-sm transition-colors ${
                activeTab === "analytics" ? "bg-emerald-500/20 text-emerald-700 dark:text-emerald-300" : "text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:text-slate-300"
              }`}
            >
              Analytics
            </button>
          </div>

          <a
            href={`${ORCHESTRATOR_URL}/api/v1/audit/export/evidence`}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1.5 rounded-full border border-slate-400 dark:border-slate-700/60 bg-white dark:bg-slate-950/40 px-2.5 py-1 text-xs font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400 transition-colors hover:text-slate-700 dark:text-slate-300"
            title="Download cryptographically signed compliance pack"
          >
            Export Pack
          </a>
          <AuditFreshnessBadge />
          <ConnectionPill connected={wsConnected} />
        </div>
      </header>

      <div className="flex min-h-0 flex-1 bg-white dark:bg-slate-950">
        <main className="flex min-w-0 flex-1 flex-col overflow-y-auto bg-black/40 p-4 sm:p-6">
            <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
              {activeTab === "recorder" ? <FlightRecorderPanel /> : <AnalyticsPanel />}
            </div>
        </main>
      </div>
    </div>
  );
}

function ConnectionPill({ connected }: { connected: boolean }) {
  return (
    <span
      className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium uppercase tracking-wider ${
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
