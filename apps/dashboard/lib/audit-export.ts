import type { AuditEvent } from "@/components/flight-recorder-panel";
import { eventSourceApp } from "@/lib/audit-source";

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// Colons are illegal in Windows filenames; browsers silently substitute them.
export function exportStamp(): string {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

// A field starting with =, +, -, or @ executes as a formula when the CSV is
// opened in Excel or Sheets. This export contains attacker-influenced text
// (tool commands), so an unescaped cell is a working injection vector in the
// very tool meant to audit one.
function csvField(value: string): string {
  const guarded = /^[=+\-@\t\r]/.test(value) ? `'${value}` : value;
  return `"${guarded.replace(/"/g, '""')}"`;
}

// Serialization is kept separate from the download so the escaping above can
// be tested directly. jsdom's Blob has no `.text()`, so a test that only sees
// the Blob cannot assert on what was actually written.
export function toAuditJsonl(events: AuditEvent[]): string {
  return events.map((ev) => JSON.stringify(ev)).join("\n");
}

export function downloadAuditJsonl(events: AuditEvent[]) {
  if (events.length === 0) return;
  const jsonl = toAuditJsonl(events);
  triggerDownload(new Blob([jsonl], { type: "application/jsonl" }), `audit-export-${exportStamp()}.jsonl`);
}

export function toAuditCsv(events: AuditEvent[]): string {
  const headers = [
    "Time",
    "Event ID",
    "Action",
    "Outcome",
    "Tool",
    "Command",
    "Source App",
    "Actor ID",
    "Correlation ID",
  ];
  const rows = events.map((ev) =>
    [
      ev.timestamp_utc || "",
      ev.event_id || "",
      ev.action?.type || "",
      ev.action?.outcome || "",
      ev.tool?.qualified || ev.tool?.name || "",
      ev.tool?.command || "",
      eventSourceApp(ev),
      ev.actor?.id || "",
      ev.correlation_id || "",
    ]
      .map((field) => csvField(String(field)))
      .join(","),
  );
  return [headers.join(","), ...rows].join("\n");
}

export function downloadAuditCsv(events: AuditEvent[]) {
  if (events.length === 0) return;
  const csv = toAuditCsv(events);
  triggerDownload(new Blob([csv], { type: "text/csv" }), `audit-export-${exportStamp()}.csv`);
}
