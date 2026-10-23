"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { RefreshCw, ShieldCheck } from "lucide-react";
import { useAgentStore } from "@/lib/store";
import { ORCHESTRATOR_URL } from "@/lib/utils";
import { apiHeaders } from "@/lib/api";
import { EmptyState, SEVERITY_DOT, SeverityBadge, TechniqueChain } from "@/components/ui/kit";
import {
  CLOSED_STATUSES,
  DISPOSITION_STATUSES,
  type Disposition,
  STATUS_LABELS,
  countUntriaged,
  dispositionKey,
  fetchDispositions,
  isTriaged,
  statusOf,
} from "@/lib/disposition";
import { FEED_FOCUS_SINCE_MINUTES } from "@/lib/feed-focus";
import { type AuditEvent, type Detection, detectionsFromEvents } from "@/components/flight-recorder-panel";
import { DetectionInvestigation } from "@/components/detection-investigation";
import { AgentTile } from "@/components/ui/agent-mark";
import { StatusChip, formatTime } from "@/components/triage-panel";

const SEV_ORDER: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };

const SEVERITIES = ["critical", "high", "medium", "low"] as const;

function detectionKey(d: Detection): string {
  return `${d.rule_id}:${d.correlation_id}`;
}

function shortSession(id: string): string {
  return id.length > 20 ? `${id.slice(0, 12)}…${id.slice(-4)}` : id;
}

export function DetectionsPanel({
  initialTriage = "all",
  initialRule = "all",
  initialDetection,
}: {
  initialTriage?: string;
  /** Opened from a rule on the Overview's top alerts. */
  initialRule?: string;
  initialDetection?: { correlationId: string; ruleId: string };
}) {
  const requestPinnedDetection = useAgentStore((s) => s.requestPinnedDetection);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [severityFilter, setSeverityFilter] = useState<string>("all");
  const [ruleFilter, setRuleFilter] = useState<string>(initialRule);
  const [triageFilter, setTriageFilter] = useState<string>(initialTriage);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [dispositions, setDispositions] = useState<Record<string, Disposition>>({});

  const load = useCallback(async () => {
    try {
      // Same trap as Analytics → Denied: the newest 500 trail lines often have
      // zero `detection` events even when stats show dozens over 7 days. Ask
      // the server for detection rows directly.
      const params = new URLSearchParams({
        limit: "500",
        scope: "all",
        focus: "detection",
        since_minutes: String(FEED_FOCUS_SINCE_MINUTES),
      });
      const res = await fetch(`${ORCHESTRATOR_URL}/api/v1/audit/tail?${params}`, {
        headers: apiHeaders(),
        credentials: "include",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setEvents((data.events ?? []) as AuditEvent[]);
      setError(null);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
    // Triage state is a separate call on purpose: a detection list that fails
    // to load is an outage, a triage list that fails is a degraded view. The
    // findings still render without it.
    try {
      setDispositions(await fetchDispositions());
    } catch {
      /* leave the last known triage state in place */
    }
  }, []);

  const applyDisposition = useCallback((updated: Disposition) => {
    setDispositions((prev) => ({
      ...prev,
      [updated.detection_key ?? dispositionKey(updated.correlation_id, updated.rule_id)]:
        updated,
    }));
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 15_000);
    return () => window.clearInterval(timer);
  }, [load]);

  const detections = useMemo(() => {
    const list = detectionsFromEvents(events);
    return [...list].sort((a, b) => {
      const sev = (SEV_ORDER[a.severity] ?? 9) - (SEV_ORDER[b.severity] ?? 9);
      if (sev !== 0) return sev;
      return (b.last_seen_utc ?? "").localeCompare(a.last_seen_utc ?? "");
    });
  }, [events]);

  // Open the detection the Overview asked for once. `detections` is rebuilt on
  // every 15-second refresh, so without the guard "All detections" lasted until
  // the next poll and the investigation reopened under the analyst.
  const appliedInitial = useRef(false);
  useEffect(() => {
    if (!initialDetection || loading || appliedInitial.current) return;
    const match = detections.find(
      (d) => d.correlation_id === initialDetection.correlationId && d.rule_id === initialDetection.ruleId,
    );
    appliedInitial.current = true;
    if (match) setSelectedKey(detectionKey(match));
  }, [detections, initialDetection, loading]);

  const ruleIds = useMemo(
    () => Array.from(new Set(detections.map((d) => d.rule_id))).sort(),
    [detections],
  );

  const counts = useMemo(() => {
    const c: Record<string, number> = { critical: 0, high: 0, medium: 0, low: 0 };
    for (const d of detections) c[d.severity] = (c[d.severity] ?? 0) + 1;
    return c;
  }, [detections]);

  const untriaged = useMemo(
    () => countUntriaged(detections, dispositions),
    [detections, dispositions],
  );

  const visible = useMemo(
    () =>
      detections.filter((d) => {
        const current = dispositions[dispositionKey(d.correlation_id, d.rule_id)];
        const triageOk =
          triageFilter === "all" ||
          (triageFilter === "untriaged" && !isTriaged(current)) ||
          (triageFilter === "open" && !CLOSED_STATUSES.has(statusOf(current))) ||
          triageFilter === statusOf(current);
        return (
          (severityFilter === "all" || d.severity === severityFilter) &&
          (ruleFilter === "all" || d.rule_id === ruleFilter) &&
          triageOk
        );
      }),
    [detections, severityFilter, ruleFilter, triageFilter, dispositions],
  );

  // From every detection, not the filtered list: recording a decision under
  // "Untriaged only" takes the finding out of that list, and the investigation
  // must not vanish under the person who just triaged it.
  const selected = useMemo(
    () => detections.find((d) => detectionKey(d) === selectedKey) ?? null,
    [detections, selectedKey],
  );

  if (selected) {
    return (
      <DetectionInvestigation
        key={detectionKey(selected)}
        det={selected}
        disposition={dispositions[dispositionKey(selected.correlation_id, selected.rule_id)]}
        onDispositionSaved={applyDisposition}
        onClose={() => setSelectedKey(null)}
        onOpenInStream={() => requestPinnedDetection(selected.correlation_id, selected.rule_id)}
      />
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {SEVERITIES.map((sev) => {
          const active = severityFilter === sev;
          const n = counts[sev] ?? 0;
          const open = detections.filter(
            (d) => d.severity === sev && !isTriaged(dispositions[dispositionKey(d.correlation_id, d.rule_id)]),
          ).length;
          return (
            <button
              key={sev}
              type="button"
              aria-pressed={active}
              onClick={() => setSeverityFilter(active ? "all" : sev)}
              className={`panel px-4 py-3 text-left transition-colors ${
                active ? "border-signal/60 ring-1 ring-signal/40" : "hover:border-foreground/25"
              }`}
            >
              <span className="flex items-center gap-2 text-[13px] font-medium capitalize text-muted-foreground">
                <span className={`h-2 w-2 rounded-full ${SEVERITY_DOT[sev]}`} />
                {sev}
              </span>
              <span className={`mt-1 block text-[28px] font-semibold leading-tight tabular-nums ${n ? "text-foreground" : "text-subtle"}`}>
                {n}
              </span>
              <span className={`block text-[12px] ${open ? "text-caution" : "text-subtle"}`}>
                {n === 0 ? "None" : open ? `${open} untriaged` : "All triaged"}
              </span>
            </button>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label="Severity"
          className="control"
          value={severityFilter}
          onChange={(e) => setSeverityFilter(e.target.value)}
        >
          <option value="all">All severities</option>
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <select
          aria-label="Rule"
          className="control"
          value={ruleFilter}
          onChange={(e) => setRuleFilter(e.target.value)}
        >
          <option value="all">All rules</option>
          {ruleIds.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
        <select
          aria-label="Triage state"
          className="control"
          value={triageFilter}
          onChange={(e) => setTriageFilter(e.target.value)}
        >
          <option value="all">All triage states</option>
          <option value="untriaged">Untriaged only</option>
          <option value="open">Open (not closed)</option>
          {DISPOSITION_STATUSES.filter((s) => s !== "new").map((s) => (
            <option key={s} value={s}>
              {STATUS_LABELS[s]}
            </option>
          ))}
        </select>
        <span className="ml-1 text-[12px] text-muted-foreground">
          <span className="font-mono text-foreground">{visible.length}</span> shown
        </span>
        {untriaged > 0 ? (
          <button
            type="button"
            onClick={() => setTriageFilter("untriaged")}
            className="inline-flex h-7 items-center rounded-sm bg-caution/15 px-2 text-[12px] font-medium text-caution transition-colors hover:bg-caution/25"
            title="A detection nobody dispositioned is an alert, not a control"
          >
            {untriaged} untriaged
          </button>
        ) : null}
        <button type="button" onClick={() => void load()} className="btn ml-auto">
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh
        </button>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-3">
        <div className="panel flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          {loading && detections.length === 0 ? (
            <EmptyState>Loading detections…</EmptyState>
          ) : error && detections.length === 0 ? (
            <EmptyState>
              <span className="text-danger">{error}</span>
            </EmptyState>
          ) : visible.length === 0 ? (
            <EmptyState icon={<ShieldCheck className="h-6 w-6" />}>
              {detections.length === 0
                ? "No detections in the last 7 days. Run agents with hooks installed, or check agentmetry doctor."
                : "No detections match these filters."}
            </EmptyState>
          ) : (
            <div className="min-h-0 flex-1 overflow-auto">
              <div className="sticky top-0 z-10 flex items-center gap-4 border-b border-border bg-card px-4 py-2">
                <span className="eyebrow shrink-0 sm:w-28">Severity</span>
                <span className="eyebrow min-w-0 flex-1">Detection</span>
                <span className="eyebrow hidden w-28 shrink-0 sm:block">Status</span>
                <span className="eyebrow hidden w-44 shrink-0 2xl:block">Techniques</span>
                <span className="eyebrow hidden w-36 shrink-0 md:block">Session</span>
                <span className="eyebrow hidden w-36 shrink-0 text-right sm:block">Last seen</span>
              </div>
              {visible.map((d) => (
                <DetectionRow
                  key={detectionKey(d)}
                  det={d}
                  disposition={dispositions[dispositionKey(d.correlation_id, d.rule_id)]}
                  selected={false}
                  onSelect={() => setSelectedKey(detectionKey(d))}
                  compact={false}
                />
              ))}
            </div>
          )}
        </div>

      </div>
    </div>
  );
}

function DetectionRow({
  det,
  disposition,
  selected,
  onSelect,
  compact,
}: {
  det: Detection;
  disposition?: Disposition;
  selected: boolean;
  onSelect: () => void;
  compact: boolean;
}) {
  const chain = det.technique_ids?.length ? det.technique_ids : det.tactic_ids;
  const status = statusOf(disposition);
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onSelect}
      className={`flex w-full items-center gap-4 border-b border-border px-4 py-3.5 text-left transition-colors last:border-b-0 ${
        selected ? "bg-muted shadow-[inset_2px_0_0_hsl(var(--signal))]" : "hover:bg-muted/60"
      }`}
    >
      <span className="shrink-0 sm:w-28">
        <SeverityBadge severity={det.severity} />
      </span>
      {det.app ? <AgentTile app={det.app} size="md" className="hidden sm:inline-flex" /> : null}
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[15px] font-semibold text-foreground">{det.title || det.rule_id}</span>
        <span className="block truncate text-[13px] text-muted-foreground">{det.summary}</span>
        <span className="mt-1.5 block sm:hidden">
          <StatusChip status={status} />
        </span>
      </span>
      <span className="hidden w-28 shrink-0 sm:block">
        <StatusChip status={status} />
      </span>
      <span className="hidden w-44 shrink-0 2xl:block">{chain?.length ? <TechniqueChain ids={chain} max={3} /> : null}</span>
      <span className={`hidden w-36 shrink-0 truncate font-mono text-[12px] text-muted-foreground ${compact ? "2xl:block" : "md:block"}`} title={det.correlation_id}>
        {shortSession(det.correlation_id)}
      </span>
      <span className={`hidden w-36 shrink-0 truncate text-right font-mono text-[12px] text-subtle ${compact ? "2xl:block" : "sm:block"}`}>
        {formatTime(det.last_seen_utc)}
      </span>
    </button>
  );
}
