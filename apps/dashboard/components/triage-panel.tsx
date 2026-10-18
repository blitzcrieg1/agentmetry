"use client";

import { useEffect, useState } from "react";
import type { Detection } from "@/components/flight-recorder-panel";
import {
  DISPOSITION_STATUSES,
  type Disposition,
  STATUS_CHIP,
  STATUS_LABELS,
  dispositionBlocker,
  saveDisposition,
  statusOf,
} from "@/lib/disposition";

export function formatTime(ts?: string): string {
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

export function StatusChip({ status }: { status: string }) {
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

const NOTE_REQUIRED_HINT: ReadonlySet<string> = new Set(["false_positive", "risk_accepted"]);

export function TriagePanel({
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
