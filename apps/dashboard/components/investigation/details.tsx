"use client";

import type { ReactNode } from "react";
import { ExternalLink, FileSearch, ListTree, ShieldAlert } from "lucide-react";
import type { Detection } from "@/components/flight-recorder-panel";
import { SeverityBadge, TechniqueChain } from "@/components/ui/kit";
import { StatusChip, TriagePanel, formatTime } from "@/components/triage-panel";
import { CodeField } from "@/components/investigation/drawer";
import { sourceLabel } from "@/lib/audit-source";
import { type Disposition, statusOf } from "@/lib/disposition";
import { type FamilyCount, kindLabel, shortSession } from "@/lib/investigation";
import { type SessionNode, type SessionTreePayload, shortTool } from "@/lib/session-tree";

export const EXPORT_OFF =
  "Session views are off in this install: AGENTMETRY_AUDIT_EXPORT_ENABLED is false, so the server does not return session events.";

function SummaryRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-1.5 text-[13px]">
      <dt className="shrink-0 text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-right">{children}</dd>
    </div>
  );
}

function Metric({ label, value, tone }: { label: string; value: ReactNode; tone?: string }) {
  return (
    <div className="rounded-md border border-border bg-background px-3 py-2.5">
      <p className={`font-mono text-[20px] font-semibold leading-none ${tone ?? ""}`}>{value}</p>
      <p className="mt-1.5 text-[12px] text-muted-foreground">{label}</p>
    </div>
  );
}

/**
 * The detection on one page: what fired, on which agent and machine, why, and
 * the calls that triggered it, with the summary and the triage decision beside
 * it. The other tabs are for digging; this one should be enough to decide.
 */
export function DetectionDetails({
  det,
  app,
  host,
  tree,
  loading,
  error,
  citedNodes,
  families,
  missing,
  disposition,
  onDispositionSaved,
  onInspect,
  onInvestigate,
  onOpenInStream,
}: {
  det: Detection;
  app: string;
  host: string;
  tree: SessionTreePayload | null;
  loading: boolean;
  error: string | null;
  citedNodes: SessionNode[];
  families: FamilyCount[];
  missing: string[];
  disposition?: Disposition;
  onDispositionSaved: (d: Disposition) => void;
  onInspect: (id: string) => void;
  onInvestigate: () => void;
  onOpenInStream: () => void;
}) {
  const agent = app ? sourceLabel(app) : "an agent";
  const chain = det.technique_ids?.length ? det.technique_ids : det.tactic_ids;
  const count = (k: "calls" | "flagged") => families.reduce((n, f) => n + f[k], 0);
  const empty = !loading && !error && (!tree || !tree.nodes.length);

  return (
    <div className="min-h-0 flex-1 overflow-auto">
      <div className="mx-auto max-w-[1400px] space-y-6 px-6 py-6">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2.5">
              <ShieldAlert className={`h-5 w-5 shrink-0 ${det.severity === "critical" || det.severity === "high" ? "text-danger" : "text-caution"}`} aria-hidden />
              <h2 className="text-[20px] font-semibold leading-tight">
                {det.title || det.rule_id}
                <span className="font-normal text-muted-foreground"> in {agent} on {host || "this machine"}</span>
              </h2>
            </div>
            <p className="mt-1 text-[13px] text-muted-foreground">{formatTime(det.first_seen_utc)}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className="btn" onClick={onInvestigate}>
              <ListTree className="h-3.5 w-3.5" /> Investigate
            </button>
            <button type="button" className="btn" onClick={onOpenInStream}>
              <ExternalLink className="h-3.5 w-3.5" /> View in event stream
            </button>
          </div>
        </header>

        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="min-w-0 space-y-6">
            <section>
              <h3 className="text-[14px] font-semibold">Why it fired</h3>
              <p className="mt-1.5 max-w-3xl text-[14px] leading-relaxed text-muted-foreground">{det.summary || "No rule summary was recorded."}</p>
            </section>

            <section className="panel overflow-hidden">
              <div className="flex items-center gap-2 border-b border-border px-4 py-3">
                <FileSearch className="h-4 w-4 text-muted-foreground" aria-hidden />
                <h3 className="text-[14px] font-semibold">Full details</h3>
              </div>
              <div className="space-y-5 p-4">
                <dl className="grid gap-x-6 gap-y-4 sm:grid-cols-2 xl:grid-cols-4">
                  {([
                    ["Detection rule", <span key="r" className="font-mono">{det.rule_id}</span>],
                    ["Severity", <SeverityBadge key="s" severity={det.severity} />],
                    ["Agent", agent],
                    ["Machine", host || "Unknown"],
                    ["Session", <span key="se" className="font-mono" title={det.correlation_id}>{shortSession(det.correlation_id)}</span>],
                    ["First seen", formatTime(det.first_seen_utc)],
                    ["Last seen", formatTime(det.last_seen_utc)],
                    ["ATT&CK", chain?.length ? <TechniqueChain key="t" ids={chain} /> : "None mapped"],
                  ] as [string, ReactNode][]).map(([k, v]) => (
                    <div key={k} className="min-w-0">
                      <dt className="eyebrow">{k}</dt>
                      <dd className="mt-1 truncate text-[13px]">{v}</dd>
                    </div>
                  ))}
                </dl>

                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <Metric label="Recorded events, whole session" value={tree?.summary.total?.toLocaleString() ?? (loading ? "…" : "—")} />
                  <Metric label="Loaded for this view" value={count("calls").toLocaleString()} />
                  <Metric label="Cited by the rule" value={citedNodes.length} tone="text-danger" />
                  <Metric label="Refused, policy or DLP" value={count("flagged")} tone={count("flagged") ? "text-caution" : undefined} />
                </div>
                {tree?.truncated ? <p className="text-[12px] text-caution">This session is longer than one view holds. The views show the window around the detection; the event stream has the rest.</p> : null}
                {missing.length && tree?.nodes.length ? (
                  <p className="text-[12px] text-caution">{missing.length} of the {(det.event_ids ?? []).length} events this detection cites are not in the trail index.</p>
                ) : null}
                {loading ? <p className="text-[12px] text-muted-foreground">Loading session evidence…</p> : null}
                {error ? <p className="text-[12px] text-danger">Could not load session evidence: {error}</p> : null}
                {empty ? (
                  <p className="text-[12px] text-muted-foreground">
                    {tree && !tree.enabled ? EXPORT_OFF : "The session is not available in the current trail index."} Detection metadata is still shown above.
                  </p>
                ) : null}

                <div className="space-y-3 border-t border-border pt-4">
                  <div className="flex items-center gap-2">
                    <ShieldAlert className="h-4 w-4 text-danger" aria-hidden />
                    <h4 className="text-[14px] font-semibold">Triggering evidence</h4>
                    <span className="text-[12px] text-subtle">calls the rule cites</span>
                  </div>
                  {citedNodes.length ? (
                    citedNodes.slice(0, 10).map((n) => (
                      <div key={n.id} className="space-y-2 rounded-md border border-danger/30 bg-danger/[0.03] p-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-mono text-[13px] font-semibold">{shortTool(n)}</span>
                          <span className="text-[12px] text-muted-foreground">{kindLabel(n)} · {formatTime(n.timestamp_utc)}</span>
                          <button type="button" className="btn ml-auto h-8 text-[12px]" onClick={() => onInspect(n.id)}>
                            <ListTree className="h-3.5 w-3.5" /> Inspect in tree
                          </button>
                        </div>
                        {n.tool.command ? (
                          <CodeField label="Command line" value={n.tool.command} note={n.tool.command_truncated ? "Cut at 4,000 characters." : undefined} />
                        ) : n.tool.input_hash ? (
                          <CodeField label="Input hash (SHA-256)" value={n.tool.input_hash} note="Command text is not recorded for this call." />
                        ) : null}
                      </div>
                    ))
                  ) : (
                    <p className="text-[12px] text-muted-foreground">{loading ? "Loading…" : "None of the cited events are in the loaded session window."}</p>
                  )}
                  {citedNodes.length > 10 ? <p className="text-[12px] text-subtle">First 10 of {citedNodes.length}. The activity table lists every one.</p> : null}
                </div>
              </div>
            </section>

            <p className="text-[12px] leading-relaxed text-subtle">
              The investigation views reconstruct recorded agent tool activity. Agentmetry does not collect host process IDs or
              parent/child process ancestry, so the tree and graph are agent activity views, not operating-system process views.
            </p>
          </div>

          <aside className="space-y-4">
            <section>
              <h3 className="text-[14px] font-semibold">Summary</h3>
              <dl className="mt-2 divide-y divide-border">
                <SummaryRow label="Severity"><SeverityBadge severity={det.severity} /></SummaryRow>
                <SummaryRow label="Agent">{agent}</SummaryRow>
                <SummaryRow label="Tactic & technique">{chain?.length ? <TechniqueChain ids={chain} /> : "None mapped"}</SummaryRow>
                <SummaryRow label="First seen"><span className="font-mono">{formatTime(det.first_seen_utc)}</span></SummaryRow>
                <SummaryRow label="Last seen"><span className="font-mono">{formatTime(det.last_seen_utc)}</span></SummaryRow>
                <SummaryRow label="Assigned to">{disposition?.assignee || <span className="text-subtle">Nobody</span>}</SummaryRow>
                <SummaryRow label="Status"><StatusChip status={statusOf(disposition)} /></SummaryRow>
              </dl>
            </section>
            <TriagePanel det={det} disposition={disposition} onSaved={onDispositionSaved} />
          </aside>
        </div>
      </div>
    </div>
  );
}
