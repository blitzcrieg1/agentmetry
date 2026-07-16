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
function exportStamp(): string {
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

export function downloadAuditJsonl(events: AuditEvent[]) {
  if (events.length === 0) return;
  const jsonl = events.map((ev) => JSON.stringify(ev)).join("\n");
  triggerDownload(new Blob([jsonl], { type: "application/jsonl" }), `audit-export-${exportStamp()}.jsonl`);
}

export function downloadAuditCsv(events: AuditEvent[]) {
  if (events.length === 0) return;
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
  const csv = [headers.join(","), ...rows].join("\n");
  triggerDownload(new Blob([csv], { type: "text/csv" }), `audit-export-${exportStamp()}.csv`);
}
