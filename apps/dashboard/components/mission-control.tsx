"use client";

import { useCallback, useEffect, useState } from "react";
import Image from "next/image";
import { Activity, FileDown, LayoutDashboard, Laptop, LogOut, ShieldAlert, Terminal } from "lucide-react";
import { useAgentStore } from "@/lib/store";
import { useWebSocket } from "@/lib/use-websocket";
import { FlightRecorderPanel, detectionsFromEvents } from "@/components/flight-recorder-panel";
import { MachinePanel } from "@/components/machine-panel";
import { AnalyticsPanel } from "@/components/analytics-panel";
import { DetectionsPanel } from "@/components/detections-panel";
import { OverviewPanel } from "@/components/overview-panel";
import { FeedStatusBar } from "@/components/feed-status-bar";
import { ThemeToggle } from "@/components/theme-toggle";
import { SignedOut } from "@/components/signed-out";
import { type SessionState, readSession, signOut } from "@/lib/session";
import { ORCHESTRATOR_URL } from "@/lib/utils";
import { apiHeaders } from "@/lib/api";
import { countUntriaged, fetchDispositions } from "@/lib/disposition";
import { FEED_FOCUS_SINCE_MINUTES } from "@/lib/feed-focus";

type Tab = "overview" | "machine" | "recorder" | "detections" | "analytics";

const PAGES: Record<Tab, { label: string; title: string; subtitle: string; icon: typeof Terminal }> = {
  overview: {
    label: "Overview",
    title: "Overview",
    subtitle: "Open investigations, hook configuration, and local trail health",
    icon: LayoutDashboard,
  },
  machine: {
    label: "This machine",
    title: "This machine",
    subtitle: "Agent hooks, settings, MCP servers, and policy on this machine",
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
    subtitle: "Correlated sequences from the last 7 days. Open one to inspect its agent session tree.",
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

/**
 * Whether this browser holds a session, checked on load and every 30 seconds.
 * A restart of the recorder drops every session, so a page left open goes
 * from signed in to signed out without anyone touching it.
 */
function useSession(): {
  state: SessionState;
  demo: boolean | null;
  recheck: () => void;
  markSignedOut: () => void;
} {
  const [state, setState] = useState<SessionState>("checking");
  const [demo, setDemo] = useState<boolean | null>(null);
  const recheck = useCallback(() => {
    void readSession().then((answer) => {
      setState(answer.state);
      // Keep the last known answer through a blip; a demo does not become live.
      if (answer.demo !== null) setDemo(answer.demo);
    });
  }, []);
  useEffect(() => {
    recheck();
    const timer = window.setInterval(recheck, 30_000);
    return () => window.clearInterval(timer);
  }, [recheck]);
  return { state, demo, recheck, markSignedOut: () => setState("signed_out") };
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
  const [detectionsView, setDetectionsView] = useState<{
    key: number;
    triage: string;
    rule?: string;
    selection?: { correlationId: string; ruleId: string };
  }>({ key: 0, triage: "all" });
  const navigate = (target: Tab, opts?: { untriaged?: boolean; rule?: string; detection?: { correlationId: string; ruleId: string } }) => {
    if (target === "detections") {
      setDetectionsView((v) => ({
        key: v.key + 1,
        triage: opts?.untriaged ? "untriaged" : "all",
        rule: opts?.rule,
        selection: opts?.detection,
      }));
    }
    setActiveTab(target);
  };
  const untriaged = useUntriagedCount(activeTab);
  const session = useSession();
  // From the server, never the URL: see `demo_mode` in core/config.py.
  const demoMode = session.demo === true;
  const [justSignedOut, setJustSignedOut] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const handleSignOut = async () => {
    setSigningOut(true);
    await signOut();
    setSigningOut(false);
    setJustSignedOut(true);
    session.markSignedOut();
  };

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
      <aside className="flex w-14 shrink-0 flex-col border-r border-border bg-card lg:w-[248px]">
        <div className="flex h-[68px] items-center justify-center gap-2.5 border-b border-border lg:justify-start lg:px-5">
          <Image
            src="/agentmetry-icon-white.svg"
            alt="Agentmetry"
            width={25}
            height={25}
            className="invert dark:invert-0"
          />
          <span className="hidden text-[16px] font-semibold tracking-tight lg:inline">Agentmetry</span>
        </div>

        {session.demo !== null ? (
          <div
            className={`mx-3 mt-4 hidden rounded-md border px-3 py-3 lg:block ${
              demoMode ? "border-caution/40 bg-caution/[0.06]" : "border-border bg-background/70"
            }`}
          >
            <div
              className={`flex items-center gap-2 text-[12px] font-medium uppercase tracking-[0.08em] ${
                demoMode ? "text-caution" : "text-subtle"
              }`}
            >
              <span className={`h-2 w-2 rounded-full ${demoMode ? "bg-caution" : "bg-secure"}`} />
              {demoMode ? "Demonstration" : "Local sensor"}
            </div>
            <p className="mt-2 text-[13px] font-medium">{demoMode ? "Sample dataset" : "This machine"}</p>
            <p className="mt-0.5 text-[12px] text-muted-foreground">{demoMode ? "Synthetic events · not live" : "Single-host view"}</p>
          </div>
        ) : null}

        <nav className="flex flex-1 flex-col gap-0.5 px-2 pt-5 lg:px-3" aria-label="Sections">
          {([
            ["Monitor", ["overview", "machine"]],
            ["Investigate", ["recorder", "detections", "analytics"]],
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
              className={`relative flex h-10 items-center justify-center gap-2.5 rounded-md text-[13px] transition-colors lg:justify-start lg:px-3 ${
                  active
                    ? "bg-muted font-medium text-foreground"
                    : "text-muted-foreground hover:bg-muted/70 hover:text-foreground"
                }`}
              >
                {active ? <span className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-signal" aria-hidden /> : null}
                <item.icon className="h-4 w-4 shrink-0" />
                <span className="hidden flex-1 text-left lg:inline">{item.label}</span>
                {badge ? (
                  <span
                    className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full bg-caution lg:static lg:h-auto lg:w-auto lg:rounded-sm lg:bg-caution/15 lg:px-1.5 lg:py-px lg:font-mono lg:text-[12px] lg:font-medium lg:text-caution"
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

        <div className="flex flex-col gap-1 border-t border-border px-2 py-3 lg:px-3">
          <a
            href={`${ORCHESTRATOR_URL}/api/v1/audit/export/evidence`}
            target="_blank"
            rel="noreferrer"
            title="Export evidence pack (SHA-256 tamper-evident)"
            className="flex h-10 items-center justify-center gap-2.5 rounded-md text-[13px] text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground lg:justify-start lg:px-3"
          >
            <FileDown className="h-4 w-4 shrink-0" />
            <span className="hidden lg:inline">Export evidence pack</span>
          </a>
          <ThemeToggle />
          {session.state === "signed_in" ? (
            <button
              type="button"
              onClick={() => void handleSignOut()}
              disabled={signingOut}
              title="Sign this browser out. Recording carries on."
              className="flex h-9 items-center justify-center gap-2.5 rounded-sm text-[13px] text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground disabled:opacity-50 lg:justify-start lg:px-2.5"
            >
              <LogOut className="h-4 w-4 shrink-0" />
              <span className="hidden lg:inline">{signingOut ? "Signing out…" : "Sign out"}</span>
              <span className="sr-only lg:hidden">Sign out</span>
            </button>
          ) : null}
          <p
            className="mt-2 hidden truncate px-3 font-mono text-[12px] text-subtle lg:block"
            title={ORCHESTRATOR_URL || shownHost()}
            suppressHydrationWarning
          >
            {shownHost()}
          </p>
        </div>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex min-h-[68px] shrink-0 flex-wrap items-center justify-between gap-x-6 gap-y-2 border-b border-border bg-card/70 px-4 py-3 lg:px-8">
          <div className="min-w-0">
            <h1 className="text-[20px] font-semibold leading-tight tracking-tight">{page.title}</h1>
            <p className="mt-1 hidden truncate text-[12px] text-muted-foreground sm:block">{page.subtitle}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {demoMode ? (
              <span className="rounded-full border border-caution/30 bg-caution/10 px-3 py-1.5 font-mono text-[12px] font-medium uppercase tracking-[0.06em] text-caution">
                Sample data · synthetic events
              </span>
            ) : null}
            <div className="flex min-h-9 items-center rounded-full border border-border bg-background px-3.5">
              <FeedStatusBar signedOut={session.state === "signed_out"} />
            </div>
          </div>
        </header>

        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-4 py-5 lg:px-8 lg:py-6">
          <div className="mx-auto flex min-h-0 w-full max-w-[1600px] flex-1 flex-col">
          {session.state === "checking" ? (
            <p className="py-10 text-center text-[13px] text-muted-foreground">Checking sign-in…</p>
          ) : session.state === "signed_out" ? (
            <SignedOut
              justSignedOut={justSignedOut}
              onCheckAgain={() => {
                setJustSignedOut(false);
                session.recheck();
              }}
            />
          ) : activeTab === "overview" ? (
            <OverviewPanel onNavigate={navigate} demo={demoMode} />
          ) : activeTab === "machine" ? (
            <MachinePanel />
          ) : activeTab === "recorder" ? (
            <FlightRecorderPanel />
          ) : activeTab === "detections" ? (
            <DetectionsPanel
              key={detectionsView.key}
              initialTriage={detectionsView.triage}
              initialRule={detectionsView.rule}
              initialDetection={detectionsView.selection}
            />
          ) : (
            <AnalyticsPanel />
          )}
          </div>
        </div>
      </main>
    </div>
  );
}
