import { describe, expect, it } from "vitest";

import {
  eventMatchesFocus,
  isInferredApproval,
  outcomeCountsAsIssue,
  outcomeFiltersForFocus,
} from "@/lib/feed-focus";

describe("outcomeFiltersForFocus", () => {
  it("keeps all outcomes for the events pill", () => {
    expect(outcomeFiltersForFocus("events")).toEqual({
      success: true,
      pending: true,
      issues: true,
    });
  });

  it("narrows to issues for denials", () => {
    expect(outcomeFiltersForFocus("denied")).toEqual({
      success: false,
      pending: false,
      issues: true,
    });
  });

  it("keeps success for DLP / policy so log-mode hits stay visible", () => {
    for (const kind of ["dlp", "policy"] as const) {
      expect(outcomeFiltersForFocus(kind)).toEqual({
        success: true,
        pending: false,
        issues: true,
      });
    }
  });
});

describe("isInferredApproval", () => {
  it("matches a synthetic approval and leaves a real tool call alone", () => {
    expect(
      isInferredApproval({
        action: { type: "approval_response", reason: "inferred:tool_ran_after_ask" },
      }),
    ).toBe(true);
    expect(
      isInferredApproval({
        action: { type: "tool_called", reason: "hook:postToolUse" },
      }),
    ).toBe(false);
  });
});

describe("outcomeCountsAsIssue", () => {
  it("keeps a degraded heartbeat, which is how a missing hook is attested", () => {
    expect(outcomeCountsAsIssue("heartbeat", "degraded")).toBe(true);
  });

  it("keeps detection severities that are not denied or error", () => {
    expect(outcomeCountsAsIssue("detection", "critical")).toBe(true);
  });

  it("leaves success, pending, and an empty outcome off the Issues chip", () => {
    expect(outcomeCountsAsIssue("tool_called", "success")).toBe(false);
    expect(outcomeCountsAsIssue("approval_request", "pending")).toBe(false);
    expect(outcomeCountsAsIssue("tool_called", "")).toBe(false);
  });
});

describe("eventMatchesFocus", () => {
  it("matches denied outcomes only for denied focus", () => {
    expect(
      eventMatchesFocus({ action: { outcome: "denied", reason: "dlp:aws" } }, "denied"),
    ).toBe(true);
    expect(
      eventMatchesFocus({ action: { outcome: "error" } }, "denied"),
    ).toBe(false);
  });

  it("matches DLP via block or reason prefix", () => {
    expect(
      eventMatchesFocus({ action: { outcome: "denied" }, dlp: { rule_id: "aws" } }, "dlp"),
    ).toBe(true);
    expect(
      eventMatchesFocus({ action: { outcome: "denied", reason: "dlp:aws_access_key" } }, "dlp"),
    ).toBe(true);
    expect(
      eventMatchesFocus({ action: { outcome: "denied", reason: "allowlist" } }, "dlp"),
    ).toBe(false);
  });

  it("matches policy blocks via tool_policy or reason", () => {
    expect(
      eventMatchesFocus(
        { action: { outcome: "denied" }, tool_policy: { blocked: true, rule_id: "r1" } },
        "policy",
      ),
    ).toBe(true);
    expect(
      eventMatchesFocus(
        { action: { outcome: "denied", reason: "tool_policy:block_shell" } },
        "policy",
      ),
    ).toBe(true);
    expect(
      eventMatchesFocus({ action: { outcome: "denied", reason: "dlp:x" } }, "policy"),
    ).toBe(false);
  });
});
