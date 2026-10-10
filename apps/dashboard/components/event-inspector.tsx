"use client";

import { useState } from "react";
import { Braces, Copy, Pin, X } from "lucide-react";
import { AuditJsonView } from "@/components/audit-json-view";
import type { AuditEvent, Detection } from "@/components/flight-recorder-panel";
import { SeverityBadge, Technique, TechniqueChain } from "@/components/ui/kit";

function copyText(text: string) {
  void navigator.clipboard?.writeText(text);
}

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
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <p className="text-[13px] font-semibold">{isDetection ? "Detection" : "Event"}</p>
          <p className="truncate font-mono text-[11px] text-subtle">{event.event_id ?? type}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-sm p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          aria-label="Close inspector"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4 text-[13px]">
        {isDetection && det ? (
          <DetectionDetail
            det={det}
            reason={event.action?.reason}
            onViewSession={onViewSession}
            onSelectEventId={onSelectEventId}
            hasEventId={hasEventId}
          />
        ) : null}

        <dl className="grid grid-cols-[6rem_1fr] gap-x-3 gap-y-2.5">
          <Field label="Time" value={event.timestamp_utc} mono />
          <Field label="Action" value={`${type}${event.action?.outcome ? `, ${event.action.outcome}` : ""}`} />
          {/* Tool / MITRE / Command describe a tool call; a detection has none, so
              they would render as blank dashes. Its evidence is the block above. */}
          {!isDetection ? (
            <>
              <Field label="Tool" value={event.tool?.qualified || event.tool?.name} mono />
              {event.tool?.mitre ? (
                <>
                  <dt className="eyebrow pt-0.5">MITRE</dt>
                  <dd className="min-w-0 space-y-1">
                    {event.tool.mitre.technique_id ? <Technique id={event.tool.mitre.technique_id} /> : null}
                    <p className="text-muted-foreground">
                      {[event.tool.mitre.tactic, event.tool.mitre.technique].filter(Boolean).join(": ")}
                    </p>
                  </dd>
                </>
              ) : null}
            </>
          ) : null}
          <Field label="Source" value={event.source?.app} />
          <Field label="Session" value={event.correlation_id} mono />
        </dl>

        {event.correlation_id && onViewSession && !isDetection ? (
          <button type="button" onClick={() => onViewSession(event.correlation_id!)} className="btn w-full">
            <Pin className="h-3.5 w-3.5" />
            Pin full session
          </button>
        ) : null}
        {!isDetection && event.tool?.command ? (
          <div>
            <p className="eyebrow mb-1.5">Command</p>
            <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded-sm border border-border bg-background p-2.5 font-mono text-[12px] leading-relaxed text-foreground">
              {event.tool.command}
            </pre>
          </div>
        ) : null}

        <div className="flex flex-wrap gap-2 border-t border-border pt-3">
          <button type="button" onClick={() => setShowRawJson(!showRawJson)} className="btn h-7 text-[12px]">
            <Braces className="h-3.5 w-3.5" />
            {showRawJson ? "Hide JSON" : "Raw JSON"}
          </button>
          <button type="button" onClick={() => copyText(JSON.stringify(event, null, 2))} className="btn h-7 text-[12px]">
            <Copy className="h-3.5 w-3.5" />
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
  const chain = det.technique_ids?.length ? det.technique_ids : det.tactic_ids;
  return (
    <div className="space-y-3 rounded-sm border border-danger/30 bg-danger/[0.05] p-3">
      <div className="flex flex-wrap items-center gap-2">
        <SeverityBadge severity={det.severity} />
        <span className="truncate font-mono text-[11px] text-muted-foreground">{det.rule_id}</span>
      </div>
      <div className="space-y-1">
        <p className="text-[14px] font-medium leading-snug">{det.title || det.rule_id}</p>
        {/* summary and reason are usually the same sentence; show reason only when
            it adds something, so the panel does not repeat itself. */}
        <p className="text-[12px] leading-relaxed text-muted-foreground">{det.summary || reason || ""}</p>
        {reason && reason !== det.summary ? (
          <p className="text-[12px] leading-relaxed text-muted-foreground">{reason}</p>
        ) : null}
      </div>

      {chain?.length ? (
        <div>
          <p className="eyebrow mb-1.5">Why it fired</p>
          <TechniqueChain ids={chain} />
        </div>
      ) : null}

      {det.event_ids?.length ? (
        <div>
          <p className="eyebrow mb-1.5">
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
                  className="truncate rounded-sm border border-border bg-card px-2 py-1 text-left font-mono text-[11px] text-foreground transition-colors hover:border-foreground/25"
                  title="Show this event"
                >
                  {id}
                </button>
              ) : (
                <span
                  key={id}
                  className="truncate rounded-sm border border-dashed border-border px-2 py-1 font-mono text-[11px] text-subtle"
                  title="Not in the current view. Pin the session to load it."
                >
                  {id}
                </span>
              );
            })}
          </div>
          {det.correlation_id && onViewSession ? (
            <button type="button" onClick={() => onViewSession(det.correlation_id)} className="btn mt-2.5 w-full">
              <Pin className="h-3.5 w-3.5" />
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
    <>
      <dt className="eyebrow pt-0.5">{label}</dt>
      <dd className={`min-w-0 break-all ${mono ? "font-mono text-[12px]" : ""} ${value ? "text-foreground" : "text-subtle"}`}>
        {value || "—"}
      </dd>
    </>
  );
}
