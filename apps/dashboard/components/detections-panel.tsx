"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ExternalLink, RefreshCw, ShieldCheck, X } from "lucide-react";
import { useAgentStore } from "@/lib/store";
import { ORCHESTRATOR_URL } from "@/lib/utils";
import { apiHeaders } from "@/lib/api";
import { eventSourceApp, sourceDotClass, sourceLabel } from "@/lib/audit-source";
import { EmptyState, SEVERITY_DOT, SeverityBadge, Technique, TechniqueChain } from "@/components/ui/kit";
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

      <div className="flex min-h-0 flex-1 flex-col gap-3 lg:flex-row">
        <div className={`panel min-h-0 min-w-0 flex-col overflow-hidden ${selected ? "hidden lg:flex lg:flex-1" : "flex flex-1"}`}>
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
                <span className={`eyebrow hidden w-36 shrink-0 ${selected ? "2xl:block" : "md:block"}`}>Session</span>
                <span className={`eyebrow hidden w-36 shrink-0 text-right ${selected ? "2xl:block" : "sm:block"}`}>Last seen</span>
              </div>
              {visible.map((d) => (
                <DetectionRow
                  key={detectionKey(d)}
                  det={d}
                  disposition={dispositions[dispositionKey(d.correlation_id, d.rule_id)]}
                  selected={detectionKey(d) === selectedKey}
                  onSelect={() => setSelectedKey(detectionKey(d))}
                  compact={selected !== null}
                />
              ))}
            </div>
          )}
        </div>

        {selected ? (
          <div className="panel flex min-h-0 w-full shrink-0 flex-col overflow-hidden lg:w-[25rem]">
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
      className={`inline-flex shrink-0 items-center rounded-sm px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset ${
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
      className={`flex w-full items-center gap-4 border-b border-border px-4 py-3 text-left transition-colors last:border-b-0 ${
        selected ? "bg-muted shadow-[inset_2px_0_0_hsl(var(--signal))]" : "hover:bg-muted/60"
      }`}
    >
      <span className="shrink-0 sm:w-28">
        <SeverityBadge severity={det.severity} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[14px] font-medium text-foreground">{det.title || det.rule_id}</span>
        <span className="block truncate text-[12px] text-muted-foreground">{det.summary}</span>
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
    <div className="space-y-2.5 rounded-sm border border-border bg-background p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="eyebrow">Triage</p>
        <StatusChip status={current} />
      </div>

      {current === "new" ? (
        <p className="text-[12px] leading-relaxed text-muted-foreground">
          No one has dispositioned this finding. Until someone does, it is an alert,
          not a control.
        </p>
      ) : null}

      <div className="flex gap-2">
        <select
          aria-label="Disposition"
          className="control min-w-0 flex-1"
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
          className="control w-32 shrink-0 placeholder:text-subtle"
          placeholder="Assignee"
          value={assignee}
          onChange={(e) => setAssignee(e.target.value)}
        />
      </div>

      <textarea
        aria-label="Triage note"
        className="control h-16 w-full resize-none py-1.5 placeholder:text-subtle"
        placeholder={
          NOTE_REQUIRED_HINT.has(status)
            ? "Required: why is this not a real finding?"
            : "Note (optional)"
        }
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />

      {error ? (
        <p className="text-[12px] text-danger">{error}</p>
      ) : blocker ? (
        <p className="text-[12px] text-muted-foreground">{blocker}</p>
      ) : null}

      <button
        type="button"
        onClick={() => void save()}
        disabled={saving || blocker !== null}
        className="btn-primary w-full"
      >
        {saving ? "Recording…" : "Record decision"}
      </button>

      {disposition?.history?.length ? (
        <div className="space-y-1.5 border-t border-border pt-2.5">
          <p className="eyebrow">Decision history</p>
          {[...disposition.history].reverse().map((entry, i) => (
            <div key={`${entry.decided_at_utc}-${i}`} className="text-[12px] text-muted-foreground">
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

  // Load the full session so triggering events resolve even when they fall
  // outside the tail window the list was built from.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetch(`${ORCHESTRATOR_URL}/api/v1/audit/session/${encodeURIComponent(det.correlation_id)}`, {
      headers: apiHeaders(),
      credentials: "include",
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
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <SeverityBadge severity={det.severity} />
          <span className="truncate font-mono text-[12px] text-muted-foreground">{det.rule_id}</span>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-sm p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          aria-label="Close detection"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-4">
        <div className="space-y-1.5">
          <p className="text-[16px] font-semibold leading-snug text-foreground">{det.title || det.rule_id}</p>
          <p className="text-[13px] leading-relaxed text-muted-foreground">{det.summary}</p>
        </div>

        {chain?.length ? (
          <div>
            <p className="eyebrow mb-2">Why it fired</p>
            <TechniqueChain ids={chain} />
          </div>
        ) : null}

        <dl className="grid grid-cols-2 gap-4">
          <div className="min-w-0">
            <dt className="eyebrow">Session</dt>
            <dd className="mt-1 truncate font-mono text-[12px]" title={det.correlation_id}>
              {shortSession(det.correlation_id)}
            </dd>
          </div>
          <div className="min-w-0">
            <dt className="eyebrow">First seen</dt>
            <dd className="mt-1 truncate font-mono text-[12px]">{formatTime(det.first_seen_utc)}</dd>
          </div>
        </dl>

        <TriagePanel det={det} disposition={disposition} onSaved={onDispositionSaved} />

        <div>
          <p className="eyebrow mb-2">
            Triggered by {det.event_ids.length} event{det.event_ids.length === 1 ? "" : "s"}
          </p>
          {loading ? (
            <p className="py-4 text-center text-[12px] text-muted-foreground">Loading events…</p>
          ) : error ? (
            <p className="py-4 text-center text-[12px] text-danger">{error}</p>
          ) : trigger.length === 0 ? (
            <p className="py-4 text-center text-[12px] text-muted-foreground">
              Triggering events are no longer in the trail.
            </p>
          ) : (
            <div className="space-y-2">
              {trigger.map((e) => (
                <TriggerEventCard key={e.event_id} event={e} />
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="border-t border-border p-3">
        <button
          type="button"
          onClick={onOpenInStream}
          className="btn w-full"
          title="Open the whole session in the event stream"
        >
          <ExternalLink className="h-3.5 w-3.5" />
          View session in event stream
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
    <div className="space-y-2 rounded-sm border border-border bg-background p-2.5">
      <div className="flex flex-wrap items-center gap-2 text-[11px]">
        <span className="font-mono text-subtle">{formatTime(event.timestamp_utc)}</span>
        <span className="inline-flex items-center gap-1.5 text-muted-foreground">
          <span className={`h-1.5 w-1.5 rounded-full ${sourceDotClass(app)}`} />
          {sourceLabel(app)}
        </span>
        <span className="truncate font-mono text-foreground" title={tool}>
          {tool}
        </span>
        {m?.technique_id ? <Technique id={m.technique_id} /> : null}
      </div>
      {event.tool?.command ? (
        <pre className="overflow-x-auto whitespace-pre-wrap break-all font-mono text-[12px] leading-relaxed text-foreground">
          {event.tool.command}
        </pre>
      ) : null}
    </div>
  );
}
