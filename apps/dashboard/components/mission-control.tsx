"use client";

import { useState } from "react";
import Image from "next/image";
import {
  Activity,
  FileCode2,
  Terminal,
} from "lucide-react";
import { useAgentStore } from "@/lib/store";
import { useWebSocket } from "@/lib/use-websocket";
import { FlightRecorderPanel } from "@/components/flight-recorder-panel";
import { AnalyticsPanel } from "@/components/analytics-panel";
import { FeedStatusBar } from "@/components/feed-status-bar";
import { ThemeToggle } from "@/components/theme-toggle";
import { ORCHESTRATOR_URL } from "@/lib/utils";

export function MissionControl() {
  useWebSocket();
  const wsConnected = useAgentStore((s) => s.wsConnected);
  const [activeTab, setActiveTab] = useState<"recorder" | "analytics">("recorder");

  const navItems = [
    { id: "recorder" as const, label: "Event stream", icon: Terminal },
    { id: "analytics" as const, label: "Analytics", icon: Activity },
  ];

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background text-foreground">
      <aside className="flex w-14 shrink-0 flex-col border-r border-border bg-card">
        <div className="flex h-14 items-center justify-center border-b border-border bg-muted/30 dark:bg-transparent">
          <Image
            src="/agentmetry-icon-white.svg"
            alt="Agentmetry"
            width={22}
            height={22}
            className="invert dark:invert-0"
          />
        </div>

        <nav className="flex flex-1 flex-col items-center gap-1 py-3">
          {navItems.map((item) => (
            <button
              key={item.id}
              type="button"
              title={item.label}
              onClick={() => setActiveTab(item.id)}
              className={`flex h-10 w-10 items-center justify-center rounded-md border transition-colors ${
                activeTab === item.id
                  ? "border-border bg-accent text-accent-foreground"
                  : "border-transparent text-muted-foreground hover:border-border hover:bg-muted hover:text-foreground"
              }`}
            >
              <item.icon className="h-4 w-4" />
            </button>
          ))}
        </nav>

        <div className="flex flex-col items-center gap-2 border-t border-border py-3">
          <ThemeToggle />
          <a
            href={`${ORCHESTRATOR_URL}/api/v1/audit/export/evidence`}
            target="_blank"
            rel="noreferrer"
            title="Export evidence pack (SHA-256 tamper-evident)"
            className="flex h-9 w-9 items-center justify-center rounded-md border border-border text-muted-foreground transition hover:bg-muted hover:text-foreground"
          >
            <FileCode2 className="h-4 w-4" />
          </a>
        </div>
      </aside>

      <main className="relative flex min-w-0 flex-1 flex-col bg-background">
        <header className="flex h-12 shrink-0 items-center justify-between border-b border-border px-4">
          <div>
            <h1 className="text-base font-semibold tracking-tight">
              {activeTab === "recorder" ? "Flight recorder" : "Analytics"}
            </h1>
            <p className="text-xs uppercase tracking-wider text-muted-foreground">
              Local SIEM · agent tool-use
            </p>
          </div>
          <div className="flex flex-col items-end gap-0.5">
            <FeedStatusBar wsConnected={wsConnected} />
            <p className="hidden font-mono text-xs text-muted-foreground sm:block">
              {ORCHESTRATOR_URL.replace(/^https?:\/\//, "")}
            </p>
          </div>
        </header>

        <div className="relative min-h-0 flex-1 p-3">
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 opacity-[0.08] dark:opacity-[0.12]"
            style={{
              backgroundImage:
                "radial-gradient(circle at 2px 2px, currentColor 1px, transparent 0)",
              backgroundSize: "24px 24px",
              color: "hsl(var(--foreground) / 0.15)",
            }}
          />
          <div className="relative z-10 flex h-full min-h-0 flex-col">
            {activeTab === "recorder" ? <FlightRecorderPanel /> : <AnalyticsPanel />}
          </div>
        </div>
      </main>
    </div>
  );
}
