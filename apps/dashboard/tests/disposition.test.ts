/**
 * Triage rules on the client — C1 from the 2026-07-24 release-readiness review.
 *
 * The backend is the authority on what a valid disposition is. These tests
 * exist to keep the two definitions from drifting: the UI must refuse the same
 * decisions the API refuses, so the operator learns before they hit Save
 * rather than through a 400 after they thought a finding was closed.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  CLOSED_STATUSES,
  DEFAULT_STATUS,
  DISPOSITION_STATUSES,
  type Disposition,
  NOTE_REQUIRED,
  STATUS_CHIP,
  STATUS_LABELS,
  countUntriaged,
  dispositionBlocker,
  dispositionKey,
  indexDispositions,
  isTriaged,
  saveDisposition,
  statusOf,
} from "@/lib/disposition";

function disposition(overrides: Partial<Disposition> = {}): Disposition {
  return {
    detection_key: "s1::r1",
    correlation_id: "s1",
    rule_id: "r1",
    status: "acknowledged",
    assignee: "",
    note: "",
    decided_by: "alex",
    decided_at_utc: "2026-07-24T10:00:00+00:00",
    first_seen_utc: "2026-07-24T10:00:00+00:00",
    history: [],
    closed: false,
    ...overrides,
  };
}

afterEach(() => vi.restoreAllMocks());

describe("status vocabulary", () => {
  it("matches the backend's list exactly", () => {
    expect([...DISPOSITION_STATUSES]).toEqual([
      "new",
      "acknowledged",
      "in_progress",
      "resolved",
      "false_positive",
      "risk_accepted",
    ]);
  });

  it("treats the same statuses as closing a finding", () => {
    expect([...CLOSED_STATUSES].sort()).toEqual([
      "false_positive",
      "resolved",
      "risk_accepted",
    ]);
  });

  it("requires a reason for the two dismissive states", () => {
    expect([...NOTE_REQUIRED].sort()).toEqual(["false_positive", "risk_accepted"]);
  });

  it("gives every status a label and a chip", () => {
    for (const status of DISPOSITION_STATUSES) {
      expect(STATUS_LABELS[status]).toBeTruthy();
      expect(STATUS_CHIP[status]).toContain("bg-");
    }
  });

  it("labels the default state as untriaged, not as a decision", () => {
    expect(STATUS_LABELS[DEFAULT_STATUS]).toBe("Untriaged");
  });
});

describe("dispositionKey", () => {
  it("matches the backend's detection_key format", () => {
    expect(dispositionKey("sess-1", "credential-exfil")).toBe(
      "sess-1::credential-exfil",
    );
  });

  it("separates the same rule in different sessions", () => {
    expect(dispositionKey("s1", "r1")).not.toBe(dispositionKey("s2", "r1"));
  });

  it("trims so a stray space cannot orphan a decision", () => {
    expect(dispositionKey(" s1 ", " r1 ")).toBe("s1::r1");
  });
});

describe("statusOf / isTriaged", () => {
  it("treats an absent disposition as untriaged", () => {
    expect(statusOf(undefined)).toBe("new");
    expect(isTriaged(undefined)).toBe(false);
    expect(isTriaged(null)).toBe(false);
  });

  it("treats an explicit new as untriaged", () => {
    expect(isTriaged(disposition({ status: "new" }))).toBe(false);
  });

  it("treats any decision as triaged", () => {
    for (const status of DISPOSITION_STATUSES.filter((s) => s !== "new")) {
      expect(isTriaged(disposition({ status }))).toBe(true);
    }
  });

  it("falls back to new for a status it does not recognize", () => {
    expect(statusOf(disposition({ status: "wontfix" }))).toBe("new");
  });
});

describe("dispositionBlocker", () => {
  it.each(["false_positive", "risk_accepted"])(
    "blocks closing as %s with no note",
    (status) => {
      expect(dispositionBlocker(status, "   ")).toContain("note is required");
    },
  );

  it.each(["false_positive", "risk_accepted"])(
    "allows closing as %s with a note",
    (status) => {
      expect(dispositionBlocker(status, "known CI bot")).toBeNull();
    },
  );

  it("allows acknowledging without a note", () => {
    expect(dispositionBlocker("acknowledged", "")).toBeNull();
  });

  it("blocks an unknown status", () => {
    expect(dispositionBlocker("wontfix", "")).toContain("Unknown status");
  });

  it("blocks a note past the backend's limit", () => {
    expect(dispositionBlocker("resolved", "x".repeat(4001))).toContain("4000");
  });
});

describe("indexDispositions / countUntriaged", () => {
  it("indexes by detection key", () => {
    const index = indexDispositions([disposition()]);
    expect(index["s1::r1"].status).toBe("acknowledged");
  });

  it("derives the key when the backend did not send one", () => {
    const index = indexDispositions([
      disposition({ detection_key: "", correlation_id: "s9", rule_id: "r9" }),
    ]);
    expect(index["s9::r9"]).toBeTruthy();
  });

  it("counts only the findings with no decision", () => {
    const index = indexDispositions([disposition()]);
    const detections = [
      { correlation_id: "s1", rule_id: "r1" },
      { correlation_id: "s2", rule_id: "r1" },
      { correlation_id: "s3", rule_id: "r2" },
    ];
    expect(countUntriaged(detections, index)).toBe(2);
  });

  it("counts nothing when everything is triaged", () => {
    const index = indexDispositions([disposition()]);
    expect(countUntriaged([{ correlation_id: "s1", rule_id: "r1" }], index)).toBe(0);
  });
});

describe("saveDisposition", () => {
  it("refuses locally rather than sending a request the API will reject", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    await expect(
      saveDisposition({ correlationId: "s1", ruleId: "r1", status: "false_positive" }),
    ).rejects.toThrow(/note is required/);
    expect(fetchSpy).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("surfaces the backend's rejection message, not a generic failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        json: async () => ({ detail: "status 'wontfix' is unknown" }),
      }),
    );
    await expect(
      saveDisposition({ correlationId: "s1", ruleId: "r1", status: "resolved" }),
    ).rejects.toThrow("status 'wontfix' is unknown");
    vi.unstubAllGlobals();
  });

  it("posts the snake_case body the API expects", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ disposition: disposition() }),
    });
    vi.stubGlobal("fetch", fetchSpy);
    await saveDisposition({
      correlationId: "s1",
      ruleId: "r1",
      status: "resolved",
      note: "fixed",
      assignee: "alex",
    });
    const body = JSON.parse(fetchSpy.mock.calls[0][1].body);
    expect(body).toMatchObject({
      correlation_id: "s1",
      rule_id: "r1",
      status: "resolved",
      note: "fixed",
      assignee: "alex",
    });
    vi.unstubAllGlobals();
  });
});
