"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowRight, Pin, RefreshCw, ShieldAlert, ShieldCheck } from "lucide-react";
import { useAgentStore } from "@/lib/store";
import { ORCHESTRATOR_URL } from "@/lib/utils";
import { apiHeaders } from "@/lib/api";
import { type AuditEvent, type Detection, detectionsFromEvents } from "@/components/flight-recorder-panel";

const SEV_ORDER: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };

const SEV_CHIP: Record<string, string> = {
  critical: "bg-red-500/15 text-red-700 ring-red-500/30 dark:text-red-300",
  high: "bg-red-500/15 text-red-700 ring-red-500/30 dark:text-red-300",
  medium: "bg-amber-500/15 text-amber-700 ring-amber-500/30 dark:text-amber-300",
  low: "bg-slate-500/15 text-slate-600 ring-slate-500/30 dark:text-slate-300",
};

const SEVERITIES = ["critical", "high", "medium", "low"] as const;

function shortSession(id: string): string {
  return id.length > 20 ? `${id.slice(0, 12)}…${id.slice(-4)}` : id;
}

function formatTime(ts?: string): string {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleString(undefined, {
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return ts;
  }
}

export function DetectionsPanel() {
  const requestPinnedDetection = useAgentStore((s) => s.requestPinnedDetection);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [severityFilter, setSeverityFilter] = useState<string>("all");
  const [ruleFilter, setRuleFilter] = useState<string>("all");

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${ORCHESTRATOR_URL}/api/v1/audit/tail?limit=500&scope=all`, {
        headers: apiHeaders(),
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

  const ruleIds = useMemo(
    () => Array.from(new Set(detections.map((d) => d.rule_id))).sort(),
    [detections],
  );

  const counts = useMemo(() => {
    const c: Record<string, number> = { critical: 0, high: 0, medium: 0, low: 0 };
    for (const d of detections) c[d.severity] = (c[d.severity] ?? 0) + 1;
    return c;
  }, [detections]);

  const visible = useMemo(
    () =>
      detections.filter(
        (d) =>
          (severityFilter === "all" || d.severity === severityFilter) &&
          (ruleFilter === "all" || d.rule_id === ruleFilter),
      ),
    [detections, severityFilter, ruleFilter],
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col rounded-lg border border-border bg-card/20">
      <div className="space-y-3 border-b border-border/60 px-3 py-3">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {SEVERITIES.map((sev) => (
            <button
              key={sev}
              type="button"
              onClick={() => setSeverityFilter(severityFilter === sev ? "all" : sev)}
              className={`rounded-md border px-3 py-2 text-left transition ${
                severityFilter === sev ? "border-border bg-muted" : "border-border/60 hover:bg-muted/50"
              }`}
            >
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{sev}</p>
              <p className={`mt-0.5 font-mono text-lg font-semibold ${counts[sev] ? "" : "text-muted-foreground"}`}>
                {counts[sev] ?? 0}
              </p>
            </button>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <select
            className="rounded-md border border-border bg-background px-2.5 py-1.5 text-sm text-muted-foreground"
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
            className="rounded-md border border-border bg-background px-2.5 py-1.5 text-sm text-muted-foreground"
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
          <span className="font-mono text-xs text-muted-foreground">{visible.length} shown</span>
          <button
            type="button"
            onClick={() => void load()}
            className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs uppercase tracking-wider text-muted-foreground transition hover:bg-muted hover:text-foreground"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {loading && detections.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">Loading detections…</p>
        ) : error && detections.length === 0 ? (
          <p className="py-8 text-center text-sm text-red-500 dark:text-red-400">{error}</p>
        ) : visible.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-12 text-center text-sm text-muted-foreground">
            <ShieldCheck className="h-6 w-6 opacity-50" />
            {detections.length === 0
              ? "No correlated detections in the loaded window. Widen capture or enable a Tier B source."
              : "No detections match these filters."}
          </div>
        ) : (
          <div className="space-y-1.5">
            {visible.map((d) => (
              <DetectionRow key={`${d.rule_id}:${d.correlation_id}`} det={d} onOpen={requestPinnedDetection} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function DetectionRow({
  det,
  onOpen,
}: {
  det: Detection;
  onOpen: (correlationId: string, ruleId: string) => void;
}) {
  const chain = det.technique_ids?.length ? det.technique_ids : det.tactic_ids;
  return (
    <button
      type="button"
      onClick={() => det.correlation_id && onOpen(det.correlation_id, det.rule_id)}
      className="flex w-full items-center gap-3 rounded-md border border-border bg-card/40 px-3 py-2.5 text-left transition hover:border-border hover:bg-muted/40"
    >
      <ShieldAlert
        className={`h-4 w-4 shrink-0 ${
          det.severity === "critical" || det.severity === "high"
            ? "text-red-500 dark:text-red-400"
            : det.severity === "medium"
              ? "text-amber-500 dark:text-amber-400"
              : "text-muted-foreground"
        }`}
      />
      <span
        className={`w-16 shrink-0 rounded px-1.5 py-0.5 text-center text-[9px] font-bold uppercase tracking-wide ring-1 ring-inset ${
          SEV_CHIP[det.severity] ?? SEV_CHIP.low
        }`}
      >
        {det.severity}
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-foreground">{det.title || det.rule_id}</p>
        <p className="truncate text-xs text-muted-foreground">{det.summary}</p>
      </div>
      {chain?.length ? (
        <div className="hidden shrink-0 items-center gap-1 font-mono text-[10px] text-muted-foreground lg:flex">
          {chain.slice(0, 3).map((t, i) => (
            <span key={`${t}-${i}`} className="inline-flex items-center gap-1">
              {i > 0 ? <ArrowRight className="h-3 w-3 opacity-50" /> : null}
              <span className="rounded bg-muted px-1 py-0.5">{t}</span>
            </span>
          ))}
        </div>
      ) : null}
      <div className="hidden w-40 shrink-0 flex-col items-end sm:flex">
        <span className="truncate font-mono text-[10px] text-muted-foreground" title={det.correlation_id}>
          {shortSession(det.correlation_id)}
        </span>
        <span className="font-mono text-[10px] text-muted-foreground/70">{formatTime(det.last_seen_utc)}</span>
      </div>
      <Pin className="h-3.5 w-3.5 shrink-0 text-muted-foreground/60" />
    </button>
  );
}
