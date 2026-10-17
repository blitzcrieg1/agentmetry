import { describe, expect, it } from "vitest";

import { bucketEvents, eventSeverity, histogramBarClass } from "@/lib/event-histogram";

describe("eventSeverity", () => {
  it("ignores an ordinary successful tool call", () => {
    expect(eventSeverity({ action: { outcome: "success" } })).toBeNull();
  });

  it("takes the worse of the outcome and the detection", () => {
    expect(
      eventSeverity({
        action: { outcome: "high" },
        detection: { severity: "critical" },
      }),
    ).toBe("critical");
  });
});

describe("bucketEvents", () => {
  it("colors a minute by the worst detection in it", () => {
    const buckets = bucketEvents([
      { timestamp_utc: "2026-10-16T15:14:10.000Z", action: { outcome: "success" } },
      { timestamp_utc: "2026-10-16T15:14:40.000Z", action: { outcome: "critical" } },
      { timestamp_utc: "2026-10-16T15:15:05.000Z", action: { outcome: "success" } },
    ]);
    const critical = buckets.find((b) => b.severity === "critical");
    const quiet = buckets.find((b) => b.count > 0 && b.severity === null);
    expect(critical?.count).toBe(2);
    expect(quiet?.count).toBe(1);
    expect(histogramBarClass(critical!)).toBe("bg-danger");
    expect(histogramBarClass(quiet!)).toContain("bg-foreground/35");
  });
});
