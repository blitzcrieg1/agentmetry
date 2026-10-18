"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import { Activity, FileDown, LayoutDashboard, Laptop, ShieldAlert, Terminal } from "lucide-react";
import { useAgentStore } from "@/lib/store";
import { useWebSocket } from "@/lib/use-websocket";
import { FlightRecorderPanel, detectionsFromEvents } from "@/components/flight-recorder-panel";
import { MachinePanel } from "@/components/machine-panel";
import { AnalyticsPanel } from "@/components/analytics-panel";
import { DetectionsPanel } from "@/components/detections-panel";
import { OverviewPanel } from "@/components/overview-panel";
import { FeedStatusBar } from "@/components/feed-status-bar";
import { ThemeToggle } from "@/components/theme-toggle";
import { ORCHESTRATOR_URL } from "@/lib/utils";
import { apiHeaders } from "@/lib/api";
import { countUntriaged, fetchDispositions } from "@/lib/disposition";
import { FEED_FOCUS_SINCE_MINUTES } from "@/lib/feed-focus";

type Tab = "overview" | "machine" | "recorder" | "detections" | "analytics";

const PAGES: Record<Tab, { label: string; title: string; subtitle: string; icon: typeof Terminal }> = {
  overview: {
    label: "Overview",
    title: "Overview",
    subtitle: "What needs a person on this machine, and whether the record can be trusted",
    icon: LayoutDashboard,
  },
  machine: {
    label: "This machine",
    title: "This machine",
    subtitle: "Agents, settings, MCP servers and policy on the machine this page is reading",
    icon: Laptop,
  },
  recorder: {
    label: "Event stream",
    title: "Event stream",
    subtitle: "Every tool call your agents made, as recorded on the trail",
    icon: Terminal,
  },
  detections: {
    label: "Detections",
    title: "Detections",
    subtitle: "Correlated sequences from the last 7 days. Open one to see its process tree.",
    icon: ShieldAlert,
  },
  analytics: {
    label: "Analytics",
    title: "Analytics",
    subtitle: "Seven days of activity, and the beta gate",
    icon: Activity,
  },
};

/**
 * Untriaged detections, for the badge beside Detections in the nav. The same
 * two calls the Detections page makes, on a slower clock. An untriaged
 * finding is the one number on this dashboard somebody has to act on, so it
 * is visible from every page rather than only the one that lists it.
 */
function useUntriagedCount(refreshKey: string): number | null {
  const [count, setCount] = useState<number | null>(null);
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const params = new URLSearchParams({
          limit: "500",
          scope: "all",
          focus: "detection",
          since_minutes: String(FEED_FOCUS_SINCE_MINUTES),
        });
        const [res, dispositions] = await Promise.all([
          fetch(`${ORCHESTRATOR_URL}/api/v1/audit/tail?${params}`, {
            headers: apiHeaders(),
            credentials: "include",
          }),
          fetchDispositions(),
        ]);
        if (!res.ok) return;
        const data = await res.json();
        if (alive) setCount(countUntriaged(detectionsFromEvents(data.events ?? []), dispositions));
      } catch {
        /* the badge is a hint; the Detections page reports real failures */
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 30_000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [refreshKey]);
  return count;
}

function shownHost(): string {
  const explicit = ORCHESTRATOR_URL.replace(/^https?:\/\//, "");
  if (explicit) return explicit;
  if (typeof window === "undefined") return "";
  return window.location.host;
}

export function MissionControl() {
  useWebSocket();
  const pinnedDetection = useAgentStore((s) => s.pinnedDetection);
  const feedFocus = useAgentStore((s) => s.feedFocus);
  const clearFeedFocus = useAgentStore((s) => s.clearFeedFocus);
  const [activeTab, setActiveTab] = useState<Tab>("overview");
  // Opening Detections from the Overview filters it to the untriaged ones; the
  // key remounts the panel so the filter applies even when it was already open.
  const [detectionsView, setDetectionsView] = useState({ key: 0, triage: "all" });
  const navigate = (target: Tab, opts?: { untriaged?: boolean }) => {
    if (target === "detections") {
      setDetectionsView((v) => ({ key: v.key + 1, triage: opts?.untriaged ? "untriaged" : "all" }));
    }
    setActiveTab(target);
  };
  const untriaged = useUntriagedCount(activeTab);

  // Opening a detection from the Detections section hands off to the flight
  // recorder, which lives in another tab — follow it there.
  useEffect(() => {
    if (pinnedDetection) setActiveTab("recorder");
  }, [pinnedDetection]);

  // Analytics stats pills: detections → Detections tab; everything else → feed.
  useEffect(() => {
    if (!feedFocus) return;
    if (feedFocus.kind === "detections") {
      setActiveTab("detections");
      clearFeedFocus();
      return;
    }
    setActiveTab("recorder");
  }, [feedFocus, clearFeedFocus]);

  const page = PAGES[activeTab];

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background text-foreground">
      <aside className="flex w-14 shrink-0 flex-col border-r border-border bg-card lg:w-[232px]">
        <div className="flex h-16 items-center justify-center gap-2.5 border-b border-border lg:justify-start lg:px-5">
          <Image
            src="/agentmetry-icon-white.svg"
            alt="Agentmetry"
            width={22}
            height={22}
            className="invert dark:invert-0"
          />
          <span className="hidden text-[15px] font-semibold tracking-tight lg:inline">Agentmetry</span>
        </div>

        <nav className="flex flex-1 flex-col gap-0.5 px-2 pt-5 lg:px-3" aria-label="Sections">
          {([
            ["Overview", ["overview", "machine"]],
            ["Activity", ["recorder", "detections", "analytics"]],
          ] as const).map(([group, ids]) => (
          <div key={group} className="mb-3">
          <p className="eyebrow mb-2 hidden px-2.5 lg:block">{group}</p>
          {ids.map((id) => {
            const item = PAGES[id];
            const active = activeTab === id;
            const badge = id === "detections" && untriaged ? untriaged : null;
            return (
              <button
                key={id}
                type="button"
                title={item.label}
                aria-current={active ? "page" : undefined}
                onClick={() => setActiveTab(id)}
                className={`relative flex h-9 items-center justify-center gap-2.5 rounded-sm text-[14px] transition-colors lg:justify-start lg:px-2.5 ${
                  active
                    ? "bg-muted font-medium text-foreground"
                    : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"
                }`}
              >
                {active ? <span className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-signal" aria-hidden /> : null}
                <item.icon className="h-4 w-4 shrink-0" />
                <span className="hidden flex-1 text-left lg:inline">{item.label}</span>
                {badge ? (
                  <span
                    className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full bg-caution lg:static lg:h-auto lg:w-auto lg:rounded-sm lg:bg-caution/15 lg:px-1.5 lg:py-px lg:font-mono lg:text-[11px] lg:font-medium lg:text-caution"
                    title={`${badge} untriaged`}
                  >
                    <span className="hidden lg:inline">{badge}</span>
                    <span className="sr-only lg:hidden">{badge} untriaged</span>
                  </span>
                ) : null}
              </button>
            );
          })}
          </div>
          ))}
        </nav>

        <div className="flex flex-col gap-0.5 border-t border-border px-2 py-3 lg:px-3">
          <a
            href={`${ORCHESTRATOR_URL}/api/v1/audit/export/evidence`}
            target="_blank"
            rel="noreferrer"
            title="Export evidence pack (SHA-256 tamper-evident)"
            className="flex h-9 items-center justify-center gap-2.5 rounded-sm text-[13px] text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground lg:justify-start lg:px-2.5"
          >
            <FileDown className="h-4 w-4 shrink-0" />
            <span className="hidden lg:inline">Export evidence pack</span>
          </a>
          <ThemeToggle />
          <p
            className="mt-2 hidden truncate px-2.5 font-mono text-[11px] text-subtle lg:block"
            title={ORCHESTRATOR_URL || shownHost()}
            suppressHydrationWarning
          >
            {shownHost()}
          </p>
        </div>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex min-h-16 shrink-0 flex-wrap items-center justify-between gap-x-6 gap-y-2 border-b border-border px-4 py-3 lg:px-7">
          <div className="min-w-0">
            <h1 className="text-[19px] font-semibold leading-tight tracking-tight">{page.title}</h1>
            <p className="mt-0.5 hidden truncate text-[13px] text-muted-foreground sm:block">{page.subtitle}</p>
          </div>
          <div className="flex h-8 items-center rounded-sm border border-border bg-card px-3">
            <FeedStatusBar />
          </div>
        </header>

        <div className="flex min-h-0 flex-1 flex-col px-4 py-4 lg:px-7 lg:py-5">
          {activeTab === "overview" ? (
            <OverviewPanel onNavigate={navigate} />
          ) : activeTab === "machine" ? (
            <MachinePanel />
          ) : activeTab === "recorder" ? (
            <FlightRecorderPanel />
          ) : activeTab === "detections" ? (
            <DetectionsPanel key={detectionsView.key} initialTriage={detectionsView.triage} />
          ) : (
            <AnalyticsPanel />
          )}
        </div>
      </main>
    </div>
  );
}
