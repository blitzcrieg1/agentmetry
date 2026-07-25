/**
 * CSV/JSONL export guards — B4 from the 2026-07-24 release-readiness review.
 *
 * The CSV path carries attacker-influenced text (agent tool commands) straight
 * into Excel or Sheets. An unescaped leading `=` there is a working formula
 * injection in the very tool meant to audit one, so these are the assertions
 * worth having a test file for at all.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AuditEvent } from "@/components/flight-recorder-panel";
import {
  downloadAuditCsv,
  downloadAuditJsonl,
  exportStamp,
  toAuditCsv,
  toAuditJsonl,
} from "@/lib/audit-export";

function event(overrides: Partial<AuditEvent> = {}): AuditEvent {
  return {
    event_id: "evt-1",
    timestamp_utc: "2026-07-24T10:00:00+00:00",
    correlation_id: "corr-1",
    action: { type: "tool_called", outcome: "success" },
    tool: { qualified: "Bash", command: "ls -la" },
    source: { app: "cursor" },
    actor: { id: "dev" },
    ...overrides,
  } as AuditEvent;
}

function withCommand(command: string): AuditEvent {
  return event({ tool: { qualified: "Bash", command } } as Partial<AuditEvent>);
}

afterEach(() => vi.restoreAllMocks());

describe("toAuditCsv", () => {
  it("neutralizes a formula-injection command", () => {
    const csv = toAuditCsv([withCommand("=cmd|'/c calc'!A1")]);
    expect(csv).toContain("\"'=cmd|'/c calc'!A1\"");
    expect(csv).not.toMatch(/,"=cmd/);
  });

  it.each(["=SUM(A1)", "+1+1", "-2+3", "@SUM(A1)", "\tlead", "\rlead"])(
    "guards a cell starting with %j",
    (command) => {
      expect(toAuditCsv([withCommand(command)])).toContain(`"'${command}"`);
    },
  );

  it("escapes embedded quotes rather than breaking the row", () => {
    const csv = toAuditCsv([withCommand('echo "hi"')]);
    expect(csv).toContain('"echo ""hi"""');
    expect(csv.split("\n")).toHaveLength(2);
  });

  it("keeps an ordinary command untouched", () => {
    const csv = toAuditCsv([event()]);
    expect(csv).toContain('"ls -la"');
    expect(csv).not.toContain("'ls -la");
  });

  it("emits a header row and one row per event", () => {
    const lines = toAuditCsv([event(), event({ event_id: "evt-2" })]).split("\n");
    expect(lines[0]).toContain("Event ID");
    expect(lines).toHaveLength(3);
  });

  it("renders a missing tool block as empty cells, not 'undefined'", () => {
    const csv = toAuditCsv([event({ tool: undefined } as Partial<AuditEvent>)]);
    expect(csv).not.toContain("undefined");
  });

  it("falls back to the unqualified tool name", () => {
    const csv = toAuditCsv([event({ tool: { name: "Read" } } as Partial<AuditEvent>)]);
    expect(csv).toContain('"Read"');
  });
});

describe("toAuditJsonl", () => {
  it("writes one JSON object per line", () => {
    const lines = toAuditJsonl([event(), event({ event_id: "evt-2" })]).split("\n");
    expect(lines).toHaveLength(2);
    expect(JSON.parse(lines[1]).event_id).toBe("evt-2");
  });

  it("round-trips an event without losing fields", () => {
    const original = event();
    expect(JSON.parse(toAuditJsonl([original]))).toEqual(original);
  });
});

describe("exportStamp", () => {
  it("produces a filename component Windows accepts", () => {
    expect(exportStamp()).not.toMatch(/[:*?"<>|\\/]/);
  });
});

describe("download wrappers", () => {
  it("export nothing for an empty selection", () => {
    const clicked = vi.spyOn(HTMLAnchorElement.prototype, "click");
    downloadAuditCsv([]);
    downloadAuditJsonl([]);
    expect(clicked).not.toHaveBeenCalled();
  });

  it("name the CSV with a .csv extension and no illegal characters", () => {
    // jsdom implements neither of these.
    Object.defineProperty(URL, "createObjectURL", { value: () => "blob:x", writable: true });
    Object.defineProperty(URL, "revokeObjectURL", { value: () => {}, writable: true });
    let name = "";
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      name = this.download;
    });
    downloadAuditCsv([event()]);
    expect(name).toMatch(/^audit-export-.*\.csv$/);
    expect(name).not.toMatch(/[:*?"<>|]/);
  });
});
