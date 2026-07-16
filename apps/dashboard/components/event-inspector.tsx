"use client";

import { useState } from "react";
import { Copy, Wrench, X } from "lucide-react";
import { AuditJsonView } from "@/components/audit-json-view";
import type { AuditEvent } from "@/components/flight-recorder-panel";

function copyText(text: string) {
  void navigator.clipboard?.writeText(text);
}

export function EventInspector({
  event,
  onClose,
  onViewSession,
}: {
  event: AuditEvent;
  onClose: () => void;
  onViewSession?: (corrId: string) => void;
}) {
  const [showRawJson, setShowRawJson] = useState(false);
  const type = event.action?.type ?? "event";
  const det = (event as AuditEvent & { detection?: Record<string, unknown> }).detection;

  return (
    <div className="flex h-full min-h-0 flex-col border-l border-border/60 bg-card/40">
      <div className="flex items-center justify-between gap-2 border-b border-border/60 px-3 py-2">
        <div className="min-w-0">
          <p className="truncate text-xs font-semibold uppercase tracking-wider text-foreground">Inspector</p>
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
        {det && typeof det === "object" ? (
          <div className="rounded border border-red-500/30 bg-red-50 p-2.5 dark:bg-red-950/20">
            <p className="text-[10px] uppercase tracking-wider text-red-700/80 dark:text-red-300/80">Detection</p>
            <p className="mt-1 font-medium text-red-900 dark:text-red-100">{String(det.title ?? det.rule_id ?? "—")}</p>
            <p className="mt-1 text-[11px] text-red-800/80 dark:text-red-200/80">{String(det.summary ?? "")}</p>
          </div>
        ) : null}

        <Field label="Time" value={event.timestamp_utc} mono />
        <Field label="Action" value={`${type}${event.action?.outcome ? ` · ${event.action.outcome}` : ""}`} />
        <Field label="Tool" value={event.tool?.qualified || event.tool?.name} />
        {event.tool?.mitre ? (
          <Field
            label="MITRE"
            value={`${event.tool.mitre.technique_id ?? ""} ${event.tool.mitre.tactic ?? ""} · ${event.tool.mitre.technique ?? ""}`.trim()}
            mono
          />
        ) : null}
        <Field label="Source" value={event.source?.app} />
        <Field label="Session" value={event.correlation_id} mono />
        {event.correlation_id && onViewSession ? (
          <button
            type="button"
            onClick={() => onViewSession(event.correlation_id!)}
            className="w-full rounded border border-sky-500/30 bg-sky-50 px-2 py-1.5 text-[11px] text-sky-800 transition hover:bg-sky-100 dark:bg-sky-950/30 dark:text-sky-200 dark:hover:bg-sky-900/40"
          >
            Pin full session
          </button>
        ) : null}
        {event.tool?.command ? (
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

function Field({ label, value, mono }: { label: string; value?: string | null; mono?: boolean }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className={`mt-0.5 break-all text-foreground/90 ${mono ? "font-mono text-[11px]" : ""}`}>{value || "—"}</p>
    </div>
  );
}
