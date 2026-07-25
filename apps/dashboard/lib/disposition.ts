import { apiHeaders } from "@/lib/api";
import { ORCHESTRATOR_URL } from "@/lib/utils";

/**
 * Detection triage. Mirrors core/audit/detection/disposition.py — the backend
 * is the authority, and every rule here exists so the operator learns about a
 * rejection before they hit Save rather than through a 400.
 */

export const DISPOSITION_STATUSES = [
  "new",
  "acknowledged",
  "in_progress",
  "resolved",
  "false_positive",
  "risk_accepted",
] as const;

export type DispositionStatus = (typeof DISPOSITION_STATUSES)[number];

export const DEFAULT_STATUS: DispositionStatus = "new";

/** States that close a finding. Nothing further is expected on these. */
export const CLOSED_STATUSES: ReadonlySet<string> = new Set([
  "resolved",
  "false_positive",
  "risk_accepted",
]);

/**
 * Closing a finding without confirming it needs a written reason. A bare
 * "false positive" is a dismissal wearing a disposition's clothes, and it is
 * the entry an auditor will question first.
 */
export const NOTE_REQUIRED: ReadonlySet<string> = new Set([
  "false_positive",
  "risk_accepted",
]);

export const STATUS_LABELS: Record<string, string> = {
  new: "Untriaged",
  acknowledged: "Acknowledged",
  in_progress: "Investigating",
  resolved: "Resolved",
  false_positive: "False positive",
  risk_accepted: "Accepted risk",
};

export const STATUS_CHIP: Record<string, string> = {
  new: "bg-amber-500/15 text-amber-700 ring-amber-500/30 dark:text-amber-300",
  acknowledged: "bg-sky-500/15 text-sky-700 ring-sky-500/30 dark:text-sky-300",
  in_progress: "bg-violet-500/15 text-violet-700 ring-violet-500/30 dark:text-violet-300",
  resolved: "bg-emerald-500/15 text-emerald-700 ring-emerald-500/30 dark:text-emerald-300",
  false_positive: "bg-slate-500/15 text-slate-600 ring-slate-500/30 dark:text-slate-300",
  risk_accepted: "bg-orange-500/15 text-orange-700 ring-orange-500/30 dark:text-orange-300",
};

export interface DispositionEntry {
  status: string;
  assignee: string;
  note: string;
  decided_by: string;
  decided_at_utc: string;
  event_id?: string;
}

export interface Disposition extends DispositionEntry {
  detection_key: string;
  correlation_id: string;
  rule_id: string;
  first_seen_utc: string;
  history: DispositionEntry[];
  closed: boolean;
}

/** Must match `detection_key()` on the backend. */
export function dispositionKey(correlationId: string, ruleId: string): string {
  return `${(correlationId ?? "").trim()}::${(ruleId ?? "").trim()}`;
}

export function statusOf(disposition?: Disposition | null): DispositionStatus {
  const status = disposition?.status;
  return (DISPOSITION_STATUSES as readonly string[]).includes(status ?? "")
    ? (status as DispositionStatus)
    : DEFAULT_STATUS;
}

export function isTriaged(disposition?: Disposition | null): boolean {
  return statusOf(disposition) !== DEFAULT_STATUS;
}

/**
 * Why this decision cannot be saved yet, or null when it can. Returning the
 * reason rather than a boolean lets the button explain itself.
 */
export function dispositionBlocker(status: string, note: string): string | null {
  if (!(DISPOSITION_STATUSES as readonly string[]).includes(status)) {
    return `Unknown status "${status}"`;
  }
  if (NOTE_REQUIRED.has(status) && !note.trim()) {
    return `A note is required to close a finding as ${STATUS_LABELS[status].toLowerCase()}`;
  }
  if (note.length > 4000) return "Note exceeds 4000 characters";
  return null;
}

export function indexDispositions(list: Disposition[]): Record<string, Disposition> {
  const index: Record<string, Disposition> = {};
  for (const entry of list) {
    index[entry.detection_key || dispositionKey(entry.correlation_id, entry.rule_id)] = entry;
  }
  return index;
}

export function countUntriaged(
  detections: { correlation_id: string; rule_id: string }[],
  index: Record<string, Disposition>,
): number {
  return detections.filter(
    (d) => !isTriaged(index[dispositionKey(d.correlation_id, d.rule_id)]),
  ).length;
}

export async function fetchDispositions(): Promise<Record<string, Disposition>> {
  const res = await fetch(`${ORCHESTRATOR_URL}/api/v1/audit/detections/dispositions/all`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  return indexDispositions((data.dispositions ?? []) as Disposition[]);
}

export async function saveDisposition(input: {
  correlationId: string;
  ruleId: string;
  status: string;
  assignee?: string;
  note?: string;
  decidedBy?: string;
  severity?: string;
}): Promise<Disposition> {
  const blocker = dispositionBlocker(input.status, input.note ?? "");
  if (blocker) throw new Error(blocker);

  const res = await fetch(`${ORCHESTRATOR_URL}/api/v1/audit/detections/disposition`, {
    method: "POST",
    headers: { ...apiHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({
      correlation_id: input.correlationId,
      rule_id: input.ruleId,
      status: input.status,
      assignee: input.assignee ?? "",
      note: input.note ?? "",
      decided_by: input.decidedBy ?? "",
      severity: input.severity ?? "",
    }),
  });
  if (!res.ok) {
    // The backend's rejection message is the useful one; do not flatten it
    // into "save failed".
    let detail = `HTTP ${res.status}`;
    try {
      detail = (await res.json())?.detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return (await res.json()).disposition as Disposition;
}
