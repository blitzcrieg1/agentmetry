/**
 * Beta gate panel logic.
 *
 * The one behaviour worth pinning is restraint. A panel that shouts on day one,
 * when nothing is wrong and four weeks simply have not elapsed, gets ignored by
 * day three. `needsAttention` is what separates "not finished yet" from
 * "something needs you".
 */
import { describe, expect, it, vi, afterEach } from "vitest";

import {
  type DogfoodReport,
  type DogfoodWeek,
  VERDICT_CHIP,
  fetchDogfood,
  needsAttention,
  weeksRemaining,
} from "@/lib/dogfood";

function week(overrides: Partial<DogfoodWeek> = {}): DogfoodWeek {
  return {
    index: 1,
    start: "2026-07-26",
    end: "2026-08-01",
    events: 500,
    active_days: 5,
    sessions: 4,
    detections: 2,
    untriaged: 0,
    complete: true,
    verdict: "GREEN",
    reasons: [],
    ...overrides,
  };
}

function report(overrides: Partial<DogfoodReport> = {}): DogfoodReport {
  return {
    started: "2026-07-26",
    consecutive_green: 1,
    required: 4,
    passed: false,
    chain_ok: true,
    chain_message: "",
    spooled: 0,
    weeks: [week()],
    ...overrides,
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("weeksRemaining", () => {
  it("counts down toward the gate", () => {
    expect(weeksRemaining(report({ consecutive_green: 1 }))).toBe(3);
  });

  it("is zero once the gate is met", () => {
    expect(weeksRemaining(report({ consecutive_green: 4, passed: true }))).toBe(0);
  });

  it("never goes negative on an overshoot", () => {
    expect(weeksRemaining(report({ consecutive_green: 6, passed: true }))).toBe(0);
  });
});

describe("needsAttention", () => {
  it("stays quiet on day one", () => {
    const day_one = report({
      consecutive_green: 0,
      weeks: [week({ complete: false, verdict: "IN PROGRESS" })],
    });
    expect(needsAttention(day_one)).toBe(false);
  });

  it("stays quiet before the clock starts", () => {
    expect(needsAttention(report({ started: null, weeks: [] }))).toBe(false);
  });

  it("does not judge a week still in progress", () => {
    const noisy_but_unfinished = report({
      weeks: [week({ complete: false, verdict: "IN PROGRESS", untriaged: 9 })],
    });
    expect(needsAttention(noisy_but_unfinished)).toBe(false);
  });

  it("speaks up for a finished week that failed", () => {
    const failed = report({
      weeks: [week({ verdict: "RED", reasons: ["only 1 active day(s)"] })],
    });
    expect(needsAttention(failed)).toBe(true);
  });

  it("speaks up for a broken chain even while everything else looks fine", () => {
    expect(needsAttention(report({ chain_ok: false }))).toBe(true);
  });

  it("speaks up for a spool that is not draining", () => {
    expect(needsAttention(report({ spooled: 42 }))).toBe(true);
  });

  it("stays quiet once the gate has passed", () => {
    const done = report({
      consecutive_green: 4,
      passed: true,
      weeks: [week(), week({ index: 2 }), week({ index: 3 }), week({ index: 4 })],
    });
    expect(needsAttention(done)).toBe(false);
  });
});

describe("verdict styling", () => {
  it("gives every verdict a chip", () => {
    for (const verdict of ["GREEN", "RED", "IN PROGRESS"] as const) {
      expect(VERDICT_CHIP[verdict]).toContain("bg-");
    }
  });

  it("does not paint a red week green", () => {
    expect(VERDICT_CHIP.RED).not.toEqual(VERDICT_CHIP.GREEN);
  });
});

describe("fetchDogfood", () => {
  it("returns the report", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: async () => report() }),
    );
    expect((await fetchDogfood()).started).toBe("2026-07-26");
  });

  it("throws on a bad response rather than rendering an empty gate", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 503 }));
    await expect(fetchDogfood()).rejects.toThrow("503");
  });
});
