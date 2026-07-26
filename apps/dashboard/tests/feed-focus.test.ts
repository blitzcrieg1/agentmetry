import { describe, expect, it } from "vitest";

import {
  eventMatchesFocus,
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
