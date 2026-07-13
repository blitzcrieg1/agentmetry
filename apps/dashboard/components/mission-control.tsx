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
import { ORCHESTRATOR_URL } from "@/lib/utils";

export function MissionControl() {
  useWebSocket();

  const [activeTab, setActiveTab] = useState<"recorder" | "analytics">("recorder");

  const wsConnected = useAgentStore((s) => s.wsConnected);

  return (
    <div className="flex h-screen flex-col">
      <header className="glass-panel relative z-20 flex items-center justify-between border-b border-zinc-800/60 px-6 py-3">
        <div className="flex items-center gap-3">
          <div className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-zinc-900/80 ring-1 ring-zinc-700/60">
            <Image
              src="/openaudit-icon-white.svg"
              alt="OpenAudit"
              width={28}
              height={28}
              priority
            />
          </div>
          <div>
            <h1 className="text-gradient text-lg font-bold tracking-tight">OpenAudit</h1>
            <p className="text-xs text-muted-foreground">SIEM flight recorder for AI agents</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex rounded-md border border-zinc-800 p-1 bg-zinc-900/50">
            <button
              onClick={() => setActiveTab("recorder")}
              className={`px-3 py-1 text-xs rounded-sm transition-colors ${
                activeTab === "recorder" ? "bg-violet-500/20 text-violet-300" : "text-zinc-500 hover:text-zinc-300"
              }`}
            >
              Flight Recorder
            </button>
            <button
              onClick={() => setActiveTab("analytics")}
              className={`px-3 py-1 text-xs rounded-sm transition-colors ${
                activeTab === "analytics" ? "bg-violet-500/20 text-violet-300" : "text-zinc-500 hover:text-zinc-300"
              }`}
            >
              Analytics
            </button>
          </div>

          <a
            href={`${ORCHESTRATOR_URL}/api/v1/audit/export/evidence`}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1.5 rounded-full border border-zinc-700/60 bg-zinc-950/40 px-2.5 py-1 text-[10px] font-medium uppercase tracking-wider text-zinc-500 transition-colors hover:text-zinc-300"
            title="Download cryptographically signed compliance pack"
          >
            Export Pack
          </a>
          <AuditFreshnessBadge />
          <ConnectionPill connected={wsConnected} />
        </div>
      </header>

      <div className="flex min-h-0 flex-1 bg-zinc-950">
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
