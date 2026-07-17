"use client";

import { useState } from "react";
import { ArrowRight, Copy, Wrench, X } from "lucide-react";
import { AuditJsonView } from "@/components/audit-json-view";
import type { AuditEvent, Detection } from "@/components/flight-recorder-panel";

function copyText(text: string) {
  void navigator.clipboard?.writeText(text);
}

const SEV_CLASS: Record<string, string> = {
  critical: "bg-red-500/15 text-red-700 ring-red-500/30 dark:text-red-300",
  high: "bg-red-500/15 text-red-700 ring-red-500/30 dark:text-red-300",
  medium: "bg-amber-500/15 text-amber-700 ring-amber-500/30 dark:text-amber-300",
  low: "bg-slate-500/15 text-slate-600 ring-slate-500/30 dark:text-slate-300",
};

export function EventInspector({
  event,
  onClose,
  onViewSession,
  onSelectEventId,
  hasEventId,
}: {
  event: AuditEvent;
  onClose: () => void;
  onViewSession?: (corrId: string) => void;
  onSelectEventId?: (eventId: string) => void;
  hasEventId?: (eventId: string) => boolean;
}) {
  const [showRawJson, setShowRawJson] = useState(false);
  const type = event.action?.type ?? "event";
  const det = event.detection;
  const isDetection = type === "detection" && det != null;

  return (
    <div className="flex h-full min-h-0 flex-col border-l border-border/60 bg-card/40">
      <div className="flex items-center justify-between gap-2 border-b border-border/60 px-3 py-2">
        <div className="min-w-0">
          <p className="truncate text-xs font-semibold uppercase tracking-wider text-foreground">
            {isDetection ? "Detection" : "Inspector"}
          </p>
          <p className="truncate font-mono text-[10px] text-muted-foreground">{event.event_id ?? type}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded border border-border p-1 text-muted-foreground transition hover:bg-muted hover:text-foreground"
          aria-label="Close inspector"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3 text-xs">
        {isDetection && det ? (
          <DetectionDetail
            det={det}
            reason={event.action?.reason}
            onViewSession={onViewSession}
            onSelectEventId={onSelectEventId}
            hasEventId={hasEventId}
          />
        ) : null}

        <Field label="Time" value={event.timestamp_utc} mono />
        <Field label="Action" value={`${type}${event.action?.outcome ? ` · ${event.action.outcome}` : ""}`} />
        {/* Tool / MITRE / Command describe a tool call; a detection has none, so
            they would render as blank dashes. Its evidence is the block above. */}
        {!isDetection ? (
          <>
            <Field label="Tool" value={event.tool?.qualified || event.tool?.name} />
            {event.tool?.mitre ? (
              <Field
                label="MITRE"
                value={`${event.tool.mitre.technique_id ?? ""} ${event.tool.mitre.tactic ?? ""} · ${event.tool.mitre.technique ?? ""}`.trim()}
                mono
              />
            ) : null}
          </>
        ) : null}
        <Field label="Source" value={event.source?.app} />
        <Field label="Session" value={event.correlation_id} mono />
        {event.correlation_id && onViewSession && !isDetection ? (
          <button
            type="button"
            onClick={() => onViewSession(event.correlation_id!)}
            className="w-full rounded border border-sky-500/30 bg-sky-50 px-2 py-1.5 text-[11px] text-sky-800 transition hover:bg-sky-100 dark:bg-sky-950/30 dark:text-sky-200 dark:hover:bg-sky-900/40"
          >
            Pin full session
          </button>
        ) : null}
        {!isDetection && event.tool?.command ? (
          <div>
            <p className="mb-1 text-[10px] uppercase tracking-wider text-muted-foreground">Command</p>
            <pre className="overflow-x-auto rounded border border-border bg-background p-2 font-mono text-[11px] text-foreground/90">
              {event.tool.command}
            </pre>
          </div>
        ) : null}

        <div className="flex flex-wrap gap-1.5 pt-1">
          <button
            type="button"
            onClick={() => setShowRawJson(!showRawJson)}
            className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-[10px] text-muted-foreground hover:bg-muted"
          >
            <Wrench className="h-3 w-3" />
            {showRawJson ? "Hide JSON" : "Raw JSON"}
          </button>
          <button
            type="button"
            onClick={() => copyText(JSON.stringify(event, null, 2))}
            className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-[10px] text-muted-foreground hover:bg-muted"
          >
            <Copy className="h-3 w-3" />
            Copy
          </button>
        </div>

        {showRawJson ? <AuditJsonView value={event} /> : null}
      </div>
    </div>
  );
}

function DetectionDetail({
  det,
  reason,
  onViewSession,
  onSelectEventId,
  hasEventId,
}: {
  det: Detection;
  reason?: string;
  onViewSession?: (corrId: string) => void;
  onSelectEventId?: (eventId: string) => void;
  hasEventId?: (eventId: string) => boolean;
}) {
  const sev = SEV_CLASS[det.severity] ?? SEV_CLASS.low;
  const chain = det.technique_ids?.length ? det.technique_ids : det.tactic_ids;
  return (
    <div className="space-y-2.5 rounded border border-red-500/30 bg-red-50 p-2.5 dark:bg-red-950/20">
      <div className="flex items-center gap-2">
        <span className={`rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide ring-1 ring-inset ${sev}`}>
          {det.severity}
        </span>
        <span className="font-mono text-[10px] text-red-700/70 dark:text-red-300/70">{det.rule_id}</span>
      </div>
      <p className="font-medium text-red-900 dark:text-red-100">{det.title || det.rule_id}</p>
      {/* summary and reason are usually the same sentence; show reason only when
          it adds something, so the panel does not repeat itself. */}
      <p className="text-[11px] text-red-800/80 dark:text-red-200/80">{det.summary || reason || ""}</p>
      {reason && reason !== det.summary ? (
        <p className="text-[11px] text-red-800/70 dark:text-red-200/70">{reason}</p>
      ) : null}

      {chain?.length ? (
        <div>
          <p className="mb-1 text-[9px] uppercase tracking-wider text-red-700/70 dark:text-red-300/70">
            Why it fired
          </p>
          <div className="flex flex-wrap items-center gap-1 font-mono text-[10px]">
            {chain.map((t, i) => (
              <span key={`${t}-${i}`} className="inline-flex items-center gap-1">
                {i > 0 ? <ArrowRight className="h-3 w-3 text-red-500/60" /> : null}
                <span className="rounded bg-red-500/10 px-1.5 py-0.5 text-red-800 ring-1 ring-inset ring-red-500/20 dark:text-red-200">
                  {t}
                </span>
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {det.event_ids?.length ? (
        <div>
          <p className="mb-1 text-[9px] uppercase tracking-wider text-red-700/70 dark:text-red-300/70">
            Triggered by {det.event_ids.length} event{det.event_ids.length === 1 ? "" : "s"}
          </p>
          <div className="flex flex-col gap-1">
            {det.event_ids.map((id) => {
              const jumpable = onSelectEventId && (!hasEventId || hasEventId(id));
              return jumpable ? (
                <button
                  key={id}
                  type="button"
                  onClick={() => onSelectEventId!(id)}
                  className="truncate rounded border border-red-500/20 bg-red-500/5 px-2 py-1 text-left font-mono text-[10px] text-red-800 transition hover:bg-red-500/15 dark:text-red-200"
                  title="Show this event"
                >
                  {id}
                </button>
              ) : (
                <span
                  key={id}
                  className="truncate rounded border border-red-500/10 px-2 py-1 font-mono text-[10px] text-red-700/60 dark:text-red-300/50"
                  title="Not in the current view — pin the session to load it"
                >
                  {id}
                </span>
              );
            })}
          </div>
          {det.correlation_id && onViewSession ? (
            <button
              type="button"
              onClick={() => onViewSession(det.correlation_id)}
              className="mt-2 w-full rounded border border-sky-500/30 bg-sky-50 px-2 py-1.5 text-[11px] text-sky-800 transition hover:bg-sky-100 dark:bg-sky-950/30 dark:text-sky-200 dark:hover:bg-sky-900/40"
            >
              Pin full session
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function Field({ label, value, mono }: { label: string; value?: string | null; mono?: boolean }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className={`mt-0.5 break-all text-foreground/90 ${mono ? "font-mono text-[11px]" : ""}`}>{value || "—"}</p>
    </div>
  );
}
