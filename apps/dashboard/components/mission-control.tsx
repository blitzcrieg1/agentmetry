"use client";

import { useState } from "react";
import Image from "next/image";
import {
  Wifi,
  WifiOff,
  Activity,
  FileCode2,
  Terminal,
} from "lucide-react";
import { useAgentStore } from "@/lib/store";
import { useWebSocket } from "@/lib/use-websocket";
import { FlightRecorderPanel } from "@/components/flight-recorder-panel";
import { AnalyticsPanel } from "@/components/analytics-panel";
import { AuditFreshnessBadge } from "@/components/audit-freshness-badge";
import { ORCHESTRATOR_URL } from "@/lib/utils";

export function MissionControl() {
  useWebSocket();
  const wsConnected = useAgentStore((s) => s.wsConnected);
  const [activeTab, setActiveTab] = useState<"recorder" | "analytics">("recorder");

  const navItems = [
    { id: "recorder", label: "Event Stream", icon: Terminal },
    { id: "analytics", label: "Analytics", icon: Activity },
  ] as const;

  return (
    <div className="flex h-screen w-full bg-background font-mono text-sm overflow-hidden">
      {/* Brutalist Sidebar */}
      <aside className="w-64 border-r border-border bg-card flex flex-col">
        <div className="p-6 border-b border-border flex items-center gap-3">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center">
            <Image src="/agentmetry-icon-white.svg" alt="Agentmetry" width={20} height={20} />
          </div>
          <div>
            <h1 className="font-bold tracking-tight text-foreground uppercase">Agentmetry</h1>
            <p className="text-[10px] text-muted-foreground uppercase tracking-widest mt-0.5">SIEM Platform</p>
          </div>
        </div>

        <nav className="flex-1 p-4 flex flex-col gap-1">
          {navItems.map((item) => (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              className={`flex items-center gap-3 px-3 py-2.5 w-full text-left transition-colors border rounded-none ${
                activeTab === item.id 
                  ? "bg-accent text-accent-foreground border-border" 
                  : "border-transparent text-muted-foreground hover:bg-muted hover:text-foreground hover:border-border"
              }`}
            >
              <item.icon className="h-4 w-4" />
              {item.label}
            </button>
          ))}
        </nav>

        <div className="p-4 border-t border-border flex flex-col gap-3 shrink-0">
          <a
            href={`${ORCHESTRATOR_URL}/api/v1/audit/export/evidence`}
            target="_blank"
            rel="noreferrer"
            className="flex items-center justify-center gap-2 border border-border bg-background px-3 py-2 text-xs font-medium uppercase tracking-wider text-muted-foreground transition-colors hover:text-foreground hover:bg-muted rounded-none"
            title="Download cryptographically signed compliance pack"
          >
            <FileCode2 className="h-4 w-4" />
            Export Pack
          </a>
          <div className="flex items-center gap-2">
            <div className="flex-1 overflow-hidden">
                <AuditFreshnessBadge />
            </div>
            <ConnectionPill connected={wsConnected} />
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col min-w-0 bg-background relative">
        <div className="absolute inset-0 z-0 opacity-20 pointer-events-none" style={{ backgroundImage: "radial-gradient(circle at 2px 2px, rgba(255,255,255,0.15) 1px, transparent 0)", backgroundSize: "32px 32px" }}></div>
        <div className="relative z-10 flex min-h-0 flex-1 flex-col p-6 overflow-hidden">
          {activeTab === "recorder" && <FlightRecorderPanel />}
          {activeTab === "analytics" && <AnalyticsPanel />}
        </div>
      </main>
    </div>
  );
}

function ConnectionPill({ connected }: { connected: boolean }) {
  return (
    <span
      className={`flex items-center gap-1.5 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider border ${
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
