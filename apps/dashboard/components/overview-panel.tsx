"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw, ShieldCheck } from "lucide-react";
import { type AuditEvent, type Detection, detectionsFromEvents } from "@/components/flight-recorder-panel";
import { EmptyState, SEVERITY_DOT, SeverityBadge, Technique } from "@/components/ui/kit";
import { apiHeaders } from "@/lib/api";
import { sourceChartColor, sourceLabel } from "@/lib/audit-source";
import { type Disposition, dispositionKey, fetchDispositions, isTriaged } from "@/lib/disposition";
import { type DogfoodReport, fetchDogfood } from "@/lib/dogfood";
import { FEED_FOCUS_SINCE_MINUTES } from "@/lib/feed-focus";
import type { MachineSnapshot } from "@/lib/machine";
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
export function OverviewPanel({ onNavigate }: { onNavigate: (target: AttentionTarget, opts?: { untriaged?: boolean }) => void }) {
  const [detections, setDetections] = useState<Detection[] | null>(null);
  const [dispositions, setDispositions] = useState<Record<string, Disposition>>({});
  const [stats, setStats] = useState<StatsSnapshot | null>(null);
  const [machine, setMachine] = useState<MachineSnapshot | null>(null);
  const [dogfood, setDogfood] = useState<DogfoodReport | null>(null);
  const [status, setStatus] = useState<StatusSnapshot | null>(null);
  const [failed, setFailed] = useState<string[]>([]);

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

  const installed = machine?.agents.filter((a) => a.state === "covered" || a.state === "uncovered") ?? [];
  const covered = installed.filter((a) => a.state === "covered").length;
  const absent = machine?.agents.filter((a) => a.state === "absent").length ?? 0;
  const maxSeverity = Math.max(1, ...SEVERITIES.map((s) => bySeverity.all[s]));
  const critOpen = bySeverity.open.critical;
  const highOpen = bySeverity.open.high;
  const mode = machine?.policy.mode;
  const spooled = status?.spool_pending ?? dogfood?.spooled ?? 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto">
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
          label="Agents recorded"
          value={machine ? `${covered}` : "…"}
          unit={machine ? `of ${installed.length}` : undefined}
          sub={
            machine
              ? `${covered === installed.length ? "Every installed agent is hooked." : `${installed.length - covered} installed agent${installed.length - covered === 1 ? " is" : "s are"} not hooked.`} ${absent} supported agent${absent === 1 ? " is" : "s are"} not installed.`
              : "Loading"
          }
          tone={machine && covered < installed.length ? "alert" : "default"}
          onClick={() => onNavigate("machine")}
        />
        <Tile
          label="Activity, 7 days"
          value={stats?.total_events != null ? stats.total_events.toLocaleString() : "…"}
          sub={stats?.sessions != null ? `events in ${stats.sessions.toLocaleString()} session${stats.sessions === 1 ? "" : "s"}` : "Loading"}
          onClick={() => onNavigate("recorder")}
        />
        <Tile
          label="Enforcement"
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
          label="Trail"
          value={dogfood ? (dogfood.chain_ok ? "Verified" : "Broken") : "…"}
          sub={dogfood ? `${dogfood.chain_message}${spooled ? `. ${spooled} waiting in the spool` : ""}` : "Loading"}
          tone={dogfood && (!dogfood.chain_ok || spooled > 0) ? "alert" : "default"}
          onClick={() => onNavigate("analytics")}
        />
      </section>

      <div className="grid min-h-0 grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <section className="panel min-w-0 p-4" aria-label="Needs attention">
          <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-[15px] font-semibold">Needs attention</h2>
            <span className="text-[12px] text-muted-foreground">Worst first. Each one opens where it gets fixed.</span>
          </div>
          {items.length === 0 ? (
            <EmptyState icon={<ShieldCheck className="h-6 w-6" />}>
              {detections && machine && dogfood ? "Nothing needs a person right now." : "Loading…"}
            </EmptyState>
          ) : (
            <ul>
              {items.map((item) => (
                <li key={item.id} className="flex flex-wrap items-center gap-3 border-t border-border py-3.5 first:border-t-0">
                  <div className="min-w-0 flex-[1_1_20rem] space-y-1">
                    <SeverityBadge severity={item.severity} />
                    <p className="text-[14px] font-medium leading-snug">{item.title}</p>
                    <p className="text-[13px] leading-relaxed text-muted-foreground">{item.body}</p>
                  </div>
                  <button
                    type="button"
                    className="btn shrink-0"
                    onClick={() => onNavigate(item.target, { untriaged: item.target === "detections" })}
                  >
                    {item.cta}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <div className="flex min-w-0 flex-col gap-4">
          <section className="panel p-4" aria-label="Events by agent">
            <div className="mb-3 flex items-baseline justify-between gap-2">
              <h2 className="text-[14px] font-semibold">Events by agent</h2>
              <span className="text-[12px] text-muted-foreground">last 7 days</span>
            </div>
            {bars.length === 0 ? (
              <p className="text-[12px] text-muted-foreground">{stats ? "No events in the last 7 days." : "Loading…"}</p>
            ) : (
              <ul className="space-y-2">
                {bars.map((bar) => (
                  <li key={bar.app} className="grid grid-cols-[6.5rem_minmax(0,1fr)_4rem] items-center gap-3">
                    <span className="truncate text-[13px]">{sourceLabel(bar.app)}</span>
                    <span className="h-2 overflow-hidden rounded-full bg-muted">
                      <span className="block h-2 rounded-full" style={{ width: `${bar.pct}%`, backgroundColor: sourceChartColor(bar.app) }} />
                    </span>
                    <span className="text-right font-mono text-[12px] text-muted-foreground">{bar.n.toLocaleString()}</span>
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
                    className="grid w-full grid-cols-[6.5rem_minmax(0,1fr)_auto] items-center gap-3 rounded-sm text-left hover:bg-muted/50"
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
                    <span className="font-mono text-[11px] text-subtle">{t.n}</span>
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
}: {
  label: string;
  value: string;
  unit?: string;
  sub: string;
  tone?: "default" | "alert";
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`panel flex min-w-0 flex-col gap-1 px-4 py-3.5 text-left transition-colors hover:border-foreground/25 ${
        tone === "alert" ? "border-danger/40 bg-danger/[0.04]" : ""
      }`}
    >
      <span className="eyebrow">{label}</span>
      <span className="text-[28px] font-semibold leading-tight tracking-tight tabular-nums">
        {value}
        {unit ? <span className="ml-1.5 text-[15px] font-medium text-muted-foreground">{unit}</span> : null}
      </span>
      <span className="text-[12px] leading-snug text-muted-foreground">{sub}</span>
    </button>
  );
}
