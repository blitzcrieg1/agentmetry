"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowRight, ExternalLink, RefreshCw, ShieldAlert, ShieldCheck, X } from "lucide-react";
import { useAgentStore } from "@/lib/store";
import { ORCHESTRATOR_URL } from "@/lib/utils";
import { apiHeaders } from "@/lib/api";
import { eventSourceApp, sourceBadgeClass, sourceLabel } from "@/lib/audit-source";
import {
  CLOSED_STATUSES,
  DISPOSITION_STATUSES,
  type Disposition,
  STATUS_CHIP,
  STATUS_LABELS,
  countUntriaged,
  dispositionBlocker,
  dispositionKey,
  fetchDispositions,
  isTriaged,
  saveDisposition,
  statusOf,
} from "@/lib/disposition";
import { FEED_FOCUS_SINCE_MINUTES } from "@/lib/feed-focus";
import { type AuditEvent, type Detection, detectionsFromEvents } from "@/components/flight-recorder-panel";

const SEV_ORDER: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };

const SEV_CHIP: Record<string, string> = {
  critical: "bg-red-500/15 text-red-700 ring-red-500/30 dark:text-red-300",
  high: "bg-red-500/15 text-red-700 ring-red-500/30 dark:text-red-300",
  medium: "bg-amber-500/15 text-amber-700 ring-amber-500/30 dark:text-amber-300",
  low: "bg-slate-500/15 text-slate-600 ring-slate-500/30 dark:text-slate-300",
};

const SEVERITIES = ["critical", "high", "medium", "low"] as const;

function detectionKey(d: Detection): string {
  return `${d.rule_id}:${d.correlation_id}`;
}

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
      second: "2-digit",
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
  const [triageFilter, setTriageFilter] = useState<string>("all");
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

  const selected = useMemo(
    () => visible.find((d) => detectionKey(d) === selectedKey) ?? null,
    [visible, selectedKey],
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
          <select
            className="rounded-md border border-border bg-background px-2.5 py-1.5 text-sm text-muted-foreground"
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
          <span className="font-mono text-xs text-muted-foreground">{visible.length} shown</span>
          {untriaged > 0 ? (
            <button
              type="button"
              onClick={() => setTriageFilter("untriaged")}
              className="rounded-md bg-amber-500/15 px-2 py-1 font-mono text-xs text-amber-700 ring-1 ring-inset ring-amber-500/30 transition hover:bg-amber-500/25 dark:text-amber-300"
              title="A detection nobody dispositioned is an alert, not a control"
            >
              {untriaged} untriaged
            </button>
          ) : null}
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

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <div className={`min-h-0 overflow-y-auto p-2 ${selected ? "hidden lg:block lg:flex-1" : "flex-1"}`}>
          {loading && detections.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">Loading detections…</p>
          ) : error && detections.length === 0 ? (
            <p className="py-8 text-center text-sm text-red-500 dark:text-red-400">{error}</p>
          ) : visible.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-12 text-center text-sm text-muted-foreground">
              <ShieldCheck className="h-6 w-6 opacity-50" />
              {detections.length === 0
                ? "No detections in the last 7 days. Run agents with hooks installed, or check agentmetry doctor."
                : "No detections match these filters."}
            </div>
          ) : (
            <div className="space-y-1.5">
              {visible.map((d) => (
                <DetectionRow
                  key={detectionKey(d)}
                  det={d}
                  disposition={dispositions[dispositionKey(d.correlation_id, d.rule_id)]}
                  selected={detectionKey(d) === selectedKey}
                  onSelect={() => setSelectedKey(detectionKey(d))}
                />
              ))}
            </div>
          )}
        </div>

        {selected ? (
          <div className="flex min-h-0 w-full shrink-0 flex-col border-t border-border/60 lg:w-[26rem] lg:border-l lg:border-t-0">
            <DetectionDetail
              det={selected}
              disposition={dispositions[dispositionKey(selected.correlation_id, selected.rule_id)]}
              onDispositionSaved={applyDisposition}
              onClose={() => setSelectedKey(null)}
              onOpenInStream={() => requestPinnedDetection(selected.correlation_id, selected.rule_id)}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}

function StatusChip({ status }: { status: string }) {
  return (
    <span
      className={`shrink-0 rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide ring-1 ring-inset ${
        STATUS_CHIP[status] ?? STATUS_CHIP.new
      }`}
    >
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}

function DetectionRow({
  det,
  disposition,
  selected,
  onSelect,
}: {
  det: Detection;
  disposition?: Disposition;
  selected: boolean;
  onSelect: () => void;
}) {
  const chain = det.technique_ids?.length ? det.technique_ids : det.tactic_ids;
  const status = statusOf(disposition);
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`flex w-full items-center gap-3 rounded-md border px-3 py-2.5 text-left transition ${
        selected
          ? "border-emerald-500/50 bg-emerald-50/60 dark:bg-emerald-950/20"
          : "border-border bg-card/40 hover:border-border hover:bg-muted/40"
      }`}
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
      <StatusChip status={status} />
      {chain?.length ? (
        <div className="hidden shrink-0 items-center gap-1 font-mono text-[10px] text-muted-foreground xl:flex">
          {chain.slice(0, 3).map((t, i) => (
            <span key={`${t}-${i}`} className="inline-flex items-center gap-1">
              {i > 0 ? <ArrowRight className="h-3 w-3 opacity-50" /> : null}
              <span className="rounded bg-muted px-1 py-0.5">{t}</span>
            </span>
          ))}
        </div>
      ) : null}
      <span
        className="hidden w-32 shrink-0 truncate text-right font-mono text-[10px] text-muted-foreground sm:block"
        title={det.correlation_id}
      >
        {shortSession(det.correlation_id)}
      </span>
    </button>
  );
}

function TriagePanel({
  det,
  disposition,
  onSaved,
}: {
  det: Detection;
  disposition?: Disposition;
  onSaved: (updated: Disposition) => void;
}) {
  const current = statusOf(disposition);
  const [status, setStatus] = useState<string>(current === "new" ? "acknowledged" : current);
  const [assignee, setAssignee] = useState(disposition?.assignee ?? "");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Switching detections must not carry the previous one's draft across, or
  // a note written about finding A gets filed against finding B.
  useEffect(() => {
    setStatus(current === "new" ? "acknowledged" : current);
    setAssignee(disposition?.assignee ?? "");
    setNote("");
    setError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [det.rule_id, det.correlation_id]);

  const blocker = dispositionBlocker(status, note);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      onSaved(
        await saveDisposition({
          correlationId: det.correlation_id,
          ruleId: det.rule_id,
          status,
          assignee,
          note,
          severity: det.severity,
        }),
      );
      setNote("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-2 rounded-md border border-border/60 bg-background/40 p-2.5">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[9px] uppercase tracking-wider text-muted-foreground">Triage</p>
        <StatusChip status={current} />
      </div>

      {current === "new" ? (
        <p className="text-[10px] leading-relaxed text-muted-foreground">
          No one has dispositioned this finding. Until someone does, it is an alert,
          not a control.
        </p>
      ) : null}

      <div className="flex gap-1.5">
        <select
          aria-label="Disposition"
          className="min-w-0 flex-1 rounded border border-border bg-background px-2 py-1.5 text-xs"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          {DISPOSITION_STATUSES.filter((s) => s !== "new").map((s) => (
            <option key={s} value={s}>
              {STATUS_LABELS[s]}
            </option>
          ))}
        </select>
        <input
          aria-label="Assignee"
          className="w-28 shrink-0 rounded border border-border bg-background px-2 py-1.5 text-xs"
          placeholder="Assignee"
          value={assignee}
          onChange={(e) => setAssignee(e.target.value)}
        />
      </div>

      <textarea
        aria-label="Triage note"
        className="h-16 w-full resize-none rounded border border-border bg-background px-2 py-1.5 text-xs"
        placeholder={
          NOTE_REQUIRED_HINT.has(status)
            ? "Required: why is this not a real finding?"
            : "Note (optional)"
        }
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />

      {error ? (
        <p className="text-[10px] text-red-500 dark:text-red-400">{error}</p>
      ) : blocker ? (
        <p className="text-[10px] text-muted-foreground">{blocker}</p>
      ) : null}

      <button
        type="button"
        onClick={() => void save()}
        disabled={saving || blocker !== null}
        className="w-full rounded border border-border px-2 py-1.5 text-[11px] uppercase tracking-wider text-muted-foreground transition hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
      >
        {saving ? "Recording…" : "Record decision"}
      </button>

      {disposition?.history?.length ? (
        <div className="space-y-1 border-t border-border/50 pt-2">
          <p className="text-[9px] uppercase tracking-wider text-muted-foreground">
            Decision history
          </p>
          {[...disposition.history].reverse().map((entry, i) => (
            <div key={`${entry.decided_at_utc}-${i}`} className="text-[10px] text-muted-foreground">
              <span className="font-mono">{formatTime(entry.decided_at_utc)}</span>{" "}
              <span className="text-foreground">{STATUS_LABELS[entry.status] ?? entry.status}</span>
              {entry.decided_by ? ` by ${entry.decided_by}` : ""}
              {entry.note ? <span className="block pl-1 italic">{entry.note}</span> : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

const NOTE_REQUIRED_HINT: ReadonlySet<string> = new Set(["false_positive", "risk_accepted"]);

function DetectionDetail({
  det,
  disposition,
  onDispositionSaved,
  onClose,
  onOpenInStream,
}: {
  det: Detection;
  disposition?: Disposition;
  onDispositionSaved: (updated: Disposition) => void;
  onClose: () => void;
  onOpenInStream: () => void;
}) {
  const [trigger, setTrigger] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const chain = det.technique_ids?.length ? det.technique_ids : det.tactic_ids;
  const sev = SEV_CHIP[det.severity] ?? SEV_CHIP.low;

  // Load the full session so triggering events resolve even when they fall
  // outside the tail window the list was built from.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetch(`${ORCHESTRATOR_URL}/api/v1/audit/session/${encodeURIComponent(det.correlation_id)}`, {
      headers: apiHeaders(),
    })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        if (cancelled) return;
        const all = (data.events ?? []) as AuditEvent[];
        const ids = new Set(det.event_ids);
        const matched = all.filter((e) => e.event_id && ids.has(e.event_id));
        // Keep the rule's own event order; fall back to timestamp.
        matched.sort((a, b) => (a.timestamp_utc ?? "").localeCompare(b.timestamp_utc ?? ""));
        setTrigger(matched);
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [det.correlation_id, det.event_ids]);

  return (
    <div className="flex h-full min-h-0 flex-col bg-card/40">
      <div className="flex items-center justify-between gap-2 border-b border-border/60 px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className={`rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide ring-1 ring-inset ${sev}`}>
            {det.severity}
          </span>
          <span className="truncate font-mono text-[10px] text-muted-foreground">{det.rule_id}</span>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded border border-border p-1 text-muted-foreground transition hover:bg-muted hover:text-foreground"
          aria-label="Close detection"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        <div>
          <p className="text-sm font-medium text-foreground">{det.title || det.rule_id}</p>
          <p className="mt-1 text-xs text-muted-foreground">{det.summary}</p>
        </div>

        {chain?.length ? (
          <div>
            <p className="mb-1 text-[9px] uppercase tracking-wider text-muted-foreground">Why it fired</p>
            <div className="flex flex-wrap items-center gap-1 font-mono text-[10px]">
              {chain.map((t, i) => (
                <span key={`${t}-${i}`} className="inline-flex items-center gap-1">
                  {i > 0 ? <ArrowRight className="h-3 w-3 text-muted-foreground/50" /> : null}
                  <span className="rounded bg-muted px-1.5 py-0.5">{t}</span>
                </span>
              ))}
            </div>
          </div>
        ) : null}

        <div className="flex items-center gap-3 border-t border-border/50 pt-2 font-mono text-[10px] text-muted-foreground">
          <span title={det.correlation_id}>{shortSession(det.correlation_id)}</span>
          <span>{formatTime(det.first_seen_utc)}</span>
        </div>

        <TriagePanel det={det} disposition={disposition} onSaved={onDispositionSaved} />

        <div>
          <p className="mb-1.5 text-[9px] uppercase tracking-wider text-muted-foreground">
            Triggered by {det.event_ids.length} event{det.event_ids.length === 1 ? "" : "s"}
          </p>
          {loading ? (
            <p className="py-4 text-center text-xs text-muted-foreground">Loading events…</p>
          ) : error ? (
            <p className="py-4 text-center text-xs text-red-500 dark:text-red-400">{error}</p>
          ) : trigger.length === 0 ? (
            <p className="py-4 text-center text-xs text-muted-foreground">
              Triggering events are no longer in the trail.
            </p>
          ) : (
            <div className="space-y-1.5">
              {trigger.map((e) => (
                <TriggerEventCard key={e.event_id} event={e} />
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="border-t border-border/60 p-3">
        <button
          type="button"
          onClick={onOpenInStream}
          className="inline-flex w-full items-center justify-center gap-1.5 rounded border border-border px-2 py-1.5 text-[11px] text-muted-foreground transition hover:bg-muted hover:text-foreground"
          title="Open the whole session in the event stream"
        >
          <ExternalLink className="h-3 w-3" />
          View entire session in event stream
        </button>
      </div>
    </div>
  );
}

function TriggerEventCard({ event }: { event: AuditEvent }) {
  const app = eventSourceApp(event);
  const m = event.tool?.mitre;
  const tool = event.tool?.qualified || event.tool?.name || event.action?.type || "event";
  return (
    <div className="space-y-1.5 rounded border border-border/60 bg-background/50 p-2">
      <div className="flex flex-wrap items-center gap-1.5 text-[10px]">
        <span className="font-mono text-muted-foreground">{formatTime(event.timestamp_utc)}</span>
        <span className={`rounded px-1 py-0.5 uppercase tracking-wide ${sourceBadgeClass(app)}`}>
          {sourceLabel(app)}
        </span>
        {m?.technique_id ? (
          <span className="rounded bg-muted px-1 py-0.5 font-mono text-red-700 dark:text-red-300">
            {m.technique_id}
          </span>
        ) : null}
      </div>
      <p className="truncate font-mono text-xs text-foreground" title={tool}>
        {tool}
      </p>
      {event.tool?.command ? (
        <pre className="overflow-x-auto rounded border border-border bg-background p-1.5 font-mono text-[10px] text-foreground/90">
          {event.tool.command}
        </pre>
      ) : null}
    </div>
  );
}
