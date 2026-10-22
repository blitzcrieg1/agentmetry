"use client";

import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { Activity, ArrowUpRight, Box, ChevronDown, ChevronUp, CircleAlert, FileCheck2, Laptop, Radio, RefreshCw, ShieldCheck, SlidersHorizontal } from "lucide-react";
import { type AuditEvent, type Detection, detectionsFromEvents } from "@/components/flight-recorder-panel";
import { DetectionTopology } from "@/components/detection-topology";
import { SEVERITY_DOT, SeverityBadge, Technique } from "@/components/ui/kit";
import { AgentTile } from "@/components/ui/agent-mark";
import { tiltHandlers } from "@/lib/use-tilt";
import { apiHeaders } from "@/lib/api";
import { displaySource, sourceChartColor, sourceLabel } from "@/lib/audit-source";
import { type Disposition, dispositionKey, fetchDispositions, isTriaged } from "@/lib/disposition";
import { type DogfoodReport, fetchDogfood } from "@/lib/dogfood";
import { FEED_FOCUS_SINCE_MINUTES } from "@/lib/feed-focus";
import { AGENT_STATE_LABEL, agentsByAttention, type MachineSnapshot } from "@/lib/machine";
import {
  type AttentionTarget,
  type StatsSnapshot,
  type StatusSnapshot,
  attentionItems,
  sourceBars,
  techniqueCounts,
} from "@/lib/overview";
import { ORCHESTRATOR_URL } from "@/lib/utils";

const SEVERITIES = ["critical", "high", "medium", "low"] as const;

function recentEventsFor(bySource: Record<string, number> | undefined, app: string): number {
  const target = displaySource(app);
  return Object.entries(bySource ?? {}).reduce(
    (total, [source, count]) => total + (displaySource(source) === target ? count : 0),
    0,
  );
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${ORCHESTRATOR_URL}${path}`, { headers: apiHeaders(), credentials: "include" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as T;
}

/**
 * The first page: what needs a person on this machine, and whether the record
 * can be trusted. Each source loads on its own, so one failing call degrades
 * one tile instead of blanking the page.
 */
export function OverviewPanel({
  onNavigate,
  demo = false,
}: {
  onNavigate: (target: AttentionTarget, opts?: { untriaged?: boolean; detection?: { correlationId: string; ruleId: string } }) => void;
  /** From the server's `demo` flag. The events are synthetic; the machine snapshot is not. */
  demo?: boolean;
}) {
  const [detections, setDetections] = useState<Detection[] | null>(null);
  const [dispositions, setDispositions] = useState<Record<string, Disposition>>({});
  const [stats, setStats] = useState<StatsSnapshot | null>(null);
  const [machine, setMachine] = useState<MachineSnapshot | null>(null);
  const [dogfood, setDogfood] = useState<DogfoodReport | null>(null);
  const [status, setStatus] = useState<StatusSnapshot | null>(null);
  const [failed, setFailed] = useState<string[]>([]);
  const [showInvestigationMap, setShowInvestigationMap] = useState(false);

  const load = useCallback(async () => {
    const params = new URLSearchParams({
      limit: "500",
      scope: "all",
      focus: "detection",
      since_minutes: String(FEED_FOCUS_SINCE_MINUTES),
    });
    const tasks: [string, () => Promise<void>][] = [
      ["detections", async () => {
        const data = await getJson<{ events?: AuditEvent[] }>(`/api/v1/audit/tail?${params}`);
        setDetections(detectionsFromEvents(data.events ?? []));
      }],
      ["triage", async () => setDispositions(await fetchDispositions())],
      ["stats", async () => setStats(await getJson<StatsSnapshot>("/api/v1/audit/stats?days=7"))],
      ["machine", async () => setMachine(await getJson<MachineSnapshot>("/api/v1/audit/machine"))],
      ["gate", async () => setDogfood(await fetchDogfood())],
      ["status", async () => setStatus(await getJson<StatusSnapshot>("/api/v1/audit/status"))],
    ];
    const results = await Promise.allSettled(tasks.map(([, run]) => run()));
    setFailed(tasks.filter((_, i) => results[i].status === "rejected").map(([name]) => name));
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 30_000);
    return () => window.clearInterval(timer);
  }, [load]);

  const untriaged = useMemo(
    () => (detections ?? []).filter((d) => !isTriaged(dispositions[dispositionKey(d.correlation_id, d.rule_id)])),
    [detections, dispositions],
  );
  const items = useMemo(
    () => attentionItems({ untriaged, stats, machine, dogfood, status }),
    [untriaged, stats, machine, dogfood, status],
  );
  const bars = useMemo(() => sourceBars(stats?.by_source), [stats]);
  const techniques = useMemo(() => techniqueCounts(detections ?? []), [detections]);
  const bySeverity = useMemo(() => {
    const all: Record<string, number> = { critical: 0, high: 0, medium: 0, low: 0 };
    const open: Record<string, number> = { critical: 0, high: 0, medium: 0, low: 0 };
    for (const d of detections ?? []) all[d.severity] = (all[d.severity] ?? 0) + 1;
    for (const d of untriaged) open[d.severity] = (open[d.severity] ?? 0) + 1;
    return { all, open };
  }, [detections, untriaged]);
  const isDetectionOpen = useCallback(
    (detection: Detection) => !isTriaged(dispositions[dispositionKey(detection.correlation_id, detection.rule_id)]),
    [dispositions],
  );

  const installed = machine?.agents.filter((a) => a.state === "covered" || a.state === "uncovered") ?? [];
  const covered = installed.filter((a) => a.state === "covered").length;
  const missingHooks = machine?.agents.filter((a) => a.state === "uncovered").length ?? 0;
  const unverifiedHooks = machine?.agents.filter((a) => a.state === "unknown").length ?? 0;
  const maxSeverity = Math.max(1, ...SEVERITIES.map((s) => bySeverity.all[s]));
  const critOpen = bySeverity.open.critical;
  const highOpen = bySeverity.open.high;
  const mode = machine?.policy.mode;
  const spooled = status?.spool_pending ?? dogfood?.spooled ?? 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto">
      <section className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-border bg-card px-4 py-3.5 shadow-[inset_0_1px_0_var(--edge),var(--elev-1)]" aria-label="Dashboard scope">
        <div className="flex min-w-0 items-start gap-3">
          <span className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-md bg-muted text-muted-foreground">
            <Laptop className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <h2 className="text-[13px] font-semibold">{demo ? "Demonstration overview" : "Local host overview"}</h2>
              <span className="rounded-full border border-border px-2 py-0.5 font-mono text-[12px] uppercase tracking-[0.06em] text-subtle">
                {demo ? "Sample data" : "Single machine"}
              </span>
            </div>
            <p className="mt-1 text-[12px] leading-relaxed text-muted-foreground">
              {demo
                ? "Events, detections and the trail are synthetic, from a demo trail. Hook configuration is read from the machine running the demo."
                : "Local install · This view reflects one machine. Hook configuration and observed events are reported separately."}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <span className="whitespace-nowrap font-mono text-[12px] uppercase tracking-[0.08em] text-subtle">Activity window · 7 days</span>
          <button
            type="button"
            className="btn"
            aria-expanded={showInvestigationMap}
            aria-controls="overview-investigation-map"
            onClick={() => setShowInvestigationMap((visible) => !visible)}
          >
            <Box className="h-3.5 w-3.5" />
            {showInvestigationMap ? "Hide 3D map" : "Show 3D map"}
            {showInvestigationMap ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          </button>
        </div>
      </section>

      {failed.length ? (
        <div className="flex items-center justify-between gap-3 rounded-sm border border-caution/40 bg-caution/[0.06] px-3 py-2 text-[12px] text-caution">
          <span>Could not load: {failed.join(", ")}. The rest of the page is current.</span>
          <button type="button" className="btn" onClick={() => void load()}>
            <RefreshCw className="h-3.5 w-3.5" />
            Retry
          </button>
        </div>
      ) : null}

      <section className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5" aria-label="Summary">
        <Tile
          label="Needs triage"
          value={detections ? untriaged.length.toLocaleString() : "…"}
          sub={
            detections
              ? untriaged.length
                ? `${critOpen} critical, ${highOpen} high, last 7 days`
                : "Every detection in the last 7 days has a decision"
              : "Loading"
          }
          tone={untriaged.length ? "alert" : "default"}
          onClick={() => onNavigate("detections", { untriaged: true })}
        />
        <Tile
          label="Hooks configured"
          value={machine ? `${covered}` : "…"}
          unit={machine ? `of ${installed.length}` : undefined}
          sub={
            machine
              ? installed.length === 0
                ? "No supported agent is installed here."
                : missingHooks || unverifiedHooks
                  ? `${missingHooks} missing · ${unverifiedHooks} unverified. Event receipt is separate.`
                  : "All installed agents have hooks configured. Event receipt is separate."
              : "Loading"
          }
          tone={missingHooks > 0 ? "alert" : "default"}
          onClick={() => onNavigate("machine")}
          extra={
            installed.length ? (
              <span className="mt-1 flex flex-wrap gap-1.5" aria-hidden>
                {installed.map((a) => (
                  <AgentTile key={a.name} app={a.name} size="sm" muted={a.state !== "covered"} />
                ))}
              </span>
            ) : null
          }
        />
        <Tile
          label="Activity, 7 days"
          value={stats?.total_events != null ? stats.total_events.toLocaleString() : "…"}
          sub={stats?.sessions != null ? `events in ${stats.sessions.toLocaleString()} session${stats.sessions === 1 ? "" : "s"}` : "Loading"}
          onClick={() => onNavigate("recorder")}
        />
        <Tile
          label="Policy mode"
          value={mode ? (mode === "block" ? "Block" : mode === "disable" ? "Off" : "Log") : "…"}
          unit={mode ? "mode" : undefined}
          sub={
            machine
              ? `${machine.policy.rules.length} tool rules, ${machine.policy.dlp_rules} DLP rules. ${mode === "block" ? "A match stops the call." : "A match is recorded and the call still runs."}`
              : "Loading"
          }
          onClick={() => onNavigate("machine")}
        />
        <Tile
          label="Local trail"
          value={dogfood ? (dogfood.chain_ok ? "Verified" : "Broken") : "…"}
          sub={dogfood ? `${dogfood.chain_message}${spooled ? `. ${spooled} waiting in the spool` : ""}` : "Loading"}
          tone={dogfood && (!dogfood.chain_ok || spooled > 0) ? "alert" : "default"}
          onClick={() => onNavigate("analytics")}
        />
      </section>

      {showInvestigationMap ? (
        <div id="overview-investigation-map">
          <DetectionTopology
            detections={detections ?? []}
            isOpen={isDetectionOpen}
            onInvestigate={(detection) => onNavigate("detections", {
              untriaged: isDetectionOpen(detection),
              detection: { correlationId: detection.correlation_id, ruleId: detection.rule_id },
            })}
          />
        </div>
      ) : null}

      <div className="grid min-h-0 grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.25fr)_minmax(340px,0.95fr)]">
        <section className="panel min-w-0 overflow-hidden" aria-label="Needs attention">
          <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4">
            <div className="flex items-center gap-3">
              <span className="grid h-9 w-9 place-items-center rounded-md bg-danger/10 text-danger">
                <CircleAlert className="h-4 w-4" />
              </span>
              <div>
                <h2 className="text-[15px] font-semibold">Needs attention</h2>
                <p className="mt-0.5 text-[12px] text-muted-foreground">Prioritized items with a direct next step</p>
              </div>
            </div>
            <span className={`rounded-full px-2.5 py-1 font-mono text-[12px] ${items.length ? "bg-danger/10 text-danger" : "bg-muted text-muted-foreground"}`}>
              {items.length} {items.length === 1 ? "item" : "items"}
            </span>
          </header>
          {items.length === 0 ? (
            <div className="px-5 py-10 text-center">
              <span className="mx-auto grid h-11 w-11 place-items-center rounded-full bg-secure/10 text-secure">
                <ShieldCheck className="h-5 w-5" />
              </span>
              <h3 className="mt-3 text-[14px] font-semibold">No open items</h3>
              <p className="mx-auto mt-1 max-w-[28rem] text-[12px] leading-relaxed text-muted-foreground">
                {detections && machine && dogfood ? "No current detections or local health findings need a decision." : "Loading the local investigation queue…"}
              </p>
            </div>
          ) : (
            <ul className="divide-y divide-border px-5">
              {items.map((item) => (
                <li key={item.id} className="flex flex-wrap items-center justify-between gap-3 py-4">
                  <div className="flex min-w-0 flex-1 items-start gap-3">
                    <span className={`mt-0.5 h-2 w-2 shrink-0 rounded-full ${SEVERITY_DOT[item.severity]}`} />
                    <div className="min-w-0 space-y-1.5">
                      <div className="flex flex-wrap items-center gap-2">
                        <SeverityBadge severity={item.severity} />
                        <span className="text-[12px] uppercase tracking-[0.06em] text-subtle">{item.target === "detections" ? "Investigation" : item.target === "machine" ? "Host configuration" : item.target === "analytics" ? "Evidence health" : "Capture health"}</span>
                      </div>
                      <p className="text-[14px] font-semibold leading-snug">{item.title}</p>
                      <p className="max-w-[58ch] text-[12px] leading-relaxed text-muted-foreground">{item.body}</p>
                    </div>
                  </div>
                  <button
                    type="button"
                    className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-md border border-border bg-background px-3 text-[12px] font-medium transition-colors hover:border-signal/40 hover:bg-signal/5"
                    onClick={() => onNavigate(item.target, { untriaged: item.target === "detections" })}
                  >
                    {item.cta}
                    <ArrowUpRight className="h-3.5 w-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <div className="flex min-w-0 flex-col gap-4">
          <section className="panel overflow-hidden" aria-label="Hook configuration and recent event receipt">
            <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-3.5">
              <div className="flex items-center gap-2.5">
                <span className="grid h-8 w-8 place-items-center rounded-md bg-muted text-muted-foreground"><Radio className="h-4 w-4" /></span>
                <div>
                  <h2 className="text-[14px] font-semibold">Capture status</h2>
                  <p className="mt-0.5 text-[12px] text-muted-foreground">Configured hooks and observed events</p>
                </div>
              </div>
              <button type="button" onClick={() => onNavigate("machine")} className="text-[12px] font-medium text-signal hover:underline">
                Details <ArrowUpRight className="ml-0.5 inline h-3 w-3" />
              </button>
            </header>
            {!machine ? (
              <p className="px-4 py-4 text-[12px] text-muted-foreground">{failed.includes("machine") ? "Hook configuration is unavailable." : "Reading hook configuration…"}</p>
            ) : (
              <ul className="divide-y divide-border px-4">
                {agentsByAttention(machine.agents).filter((agent) => agent.state !== "absent").slice(0, 6).map((agent) => {
                  const observed = recentEventsFor(status?.by_source, agent.name);
                  const stateTone = agent.state === "covered"
                    ? "border-border bg-muted/60 text-foreground"
                    : agent.state === "uncovered"
                      ? "border-danger/20 bg-danger/5 text-danger"
                      : "border-caution/20 bg-caution/5 text-caution";
                  return (
                    <li key={agent.name} className="flex items-center justify-between gap-3 py-2.5">
                      <div className="flex min-w-0 items-center gap-2.5">
                        <AgentTile app={agent.name} size="sm" />
                        <div className="min-w-0">
                          <p className="truncate text-[12px] font-medium">{sourceLabel(agent.name)}</p>
                          <p className="mt-0.5 text-[12px] text-muted-foreground">
                            {status ? observed ? `${observed.toLocaleString()} recent events` : "No recent events" : failed.includes("status") ? "Event status unavailable" : "Checking event receipt…"}
                          </p>
                        </div>
                      </div>
                      <span className={`whitespace-nowrap rounded-full border px-2 py-1 text-[12px] font-medium ${stateTone}`}>
                        {AGENT_STATE_LABEL[agent.state]}
                      </span>
                    </li>
                  );
                })}
                {machine.agents.every((agent) => agent.state === "absent") ? (
                  <li className="py-4 text-[12px] text-muted-foreground">No supported agent is installed on this machine.</li>
                ) : null}
              </ul>
            )}
            <div className="flex items-start gap-2 border-t border-border bg-muted/40 px-4 py-3 text-[12px] leading-relaxed text-muted-foreground">
              <Activity className="mt-0.5 h-3.5 w-3.5 shrink-0 text-subtle" />
              A configured hook does not prove capture. Recent event receipt is shown separately.
            </div>
          </section>

          <section className="panel p-4" aria-label="Events by agent">
            <div className="mb-3 flex items-baseline justify-between gap-2">
              <h2 className="text-[14px] font-semibold">Activity by agent</h2>
              <span className="text-[12px] uppercase tracking-[0.06em] text-subtle">last 7 days</span>
            </div>
            {bars.length === 0 ? (
              <p className="text-[12px] text-muted-foreground">{stats ? "No events in the last 7 days." : "Loading…"}</p>
            ) : (
              <ul className="space-y-2">
                {bars.map((bar) => (
                  <li key={bar.app} className="grid grid-cols-[9rem_minmax(0,1fr)_4.5rem] items-center gap-3">
                    <span className="flex min-w-0 items-center gap-2">
                      <AgentTile app={bar.app} size="sm" />
                      <span className="truncate text-[14px]">{sourceLabel(bar.app)}</span>
                    </span>
                    <span className="h-2.5 overflow-hidden rounded-full bg-muted">
                      <span className="block h-2.5 rounded-full" style={{ width: `${bar.pct}%`, backgroundColor: sourceChartColor(bar.app) }} />
                    </span>
                    <span className="text-right font-mono text-[13px] text-foreground">{bar.n.toLocaleString()}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="panel p-4" aria-label="Detections by severity">
            <div className="mb-3 flex items-baseline justify-between gap-2">
              <h2 className="text-[14px] font-semibold">Detections by severity</h2>
              <span className="text-[12px] text-muted-foreground">
                last 7 days{detections ? `, ${detections.length} in all` : ""}
              </span>
            </div>
            <ul className="space-y-2">
              {SEVERITIES.map((sev) => (
                <li key={sev}>
                  <button
                    type="button"
                    onClick={() => onNavigate("detections")}
                    className="grid w-full grid-cols-[6.5rem_minmax(0,1fr)_auto] items-center gap-3 rounded-md px-1 py-1 text-left hover:bg-muted/50"
                  >
                    <span className="text-[13px] capitalize">{sev}</span>
                    <span className="h-2 overflow-hidden rounded-full bg-muted">
                      <span
                        className={`block h-2 rounded-full ${SEVERITY_DOT[sev]}`}
                        style={{ width: `${(bySeverity.all[sev] / maxSeverity) * 100}%` }}
                      />
                    </span>
                    <span className="whitespace-nowrap text-right font-mono text-[12px] text-muted-foreground">
                      {bySeverity.all[sev]}
                      {bySeverity.open[sev] ? <span className="text-caution"> ({bySeverity.open[sev]} open)</span> : null}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>

          <section className="panel p-4" aria-label="ATT&CK techniques seen">
            <div className="mb-3 flex items-baseline justify-between gap-2">
              <h2 className="text-[14px] font-semibold">ATT&amp;CK techniques seen</h2>
              <span className="text-[12px] text-muted-foreground">in detections, 7 days</span>
            </div>
            {techniques.length === 0 ? (
              <p className="text-[12px] text-muted-foreground">{detections ? "None." : "Loading…"}</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {techniques.map((t) => (
                  <span key={t.id} className="inline-flex items-center gap-1.5">
                    <Technique id={t.id} />
                    <span className="font-mono text-[12px] text-subtle">{t.n}</span>
                  </span>
                ))}
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function Tile({
  label,
  value,
  unit,
  sub,
  tone = "default",
  onClick,
  extra,
}: {
  label: string;
  value: string;
  unit?: string;
  sub: string;
  tone?: "default" | "alert";
  onClick: () => void;
  extra?: ReactNode;
}) {
  const icons = {
    "Needs triage": CircleAlert,
    "Hooks configured": Radio,
    "Activity, 7 days": Activity,
    "Policy mode": SlidersHorizontal,
    "Local trail": FileCheck2,
  } as const;
  const Icon = icons[label as keyof typeof icons] ?? Activity;

  return (
    <button
      type="button"
      onClick={onClick}
      {...tiltHandlers()}
      className={`panel tilt flex min-w-0 flex-col gap-2.5 rounded-lg px-4 py-4 text-left hover:border-foreground/30 ${
        tone === "alert" ? "border-danger/50 bg-danger/[0.06]" : ""
      }`}
    >
      <span className="flex items-center justify-between gap-2">
        <span className="eyebrow">{label}</span>
        <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-md ${tone === "alert" ? "bg-danger/10 text-danger" : "bg-muted text-subtle"}`}>
          <Icon className="h-4 w-4" />
        </span>
      </span>
      <span className="text-[28px] font-semibold leading-none tracking-tight tabular-nums">
        {value}
        {unit ? <span className="ml-1.5 text-[13px] font-medium text-muted-foreground">{unit}</span> : null}
      </span>
      <span className="text-[12px] leading-relaxed text-muted-foreground">{sub}</span>
      {extra}
    </button>
  );
}
