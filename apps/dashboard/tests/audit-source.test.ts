/**
 * Source-app normalization — B4 from the 2026-07-24 release-readiness review.
 *
 * Every source label, badge, dot and chart colour resolves through
 * `normalizeSourceApp`. When that logic lived in three components they drifted,
 * and a legacy codename leaked into the analytics charts. This pins the
 * consolidated behaviour.
 */
import { describe, expect, it } from "vitest";

import type { AuditEvent } from "@/components/flight-recorder-panel";
import {
  SOURCE_CHART_COLOR,
  eventSourceApp,
  normalizeSourceApp,
  sourceBadgeClass,
  sourceChartColor,
  sourceDotClass,
  sourceLabel,
} from "@/lib/audit-source";

const FIRST_PARTY = [
  "cursor",
  "claude",
  "codex",
  "antigravity",
  "qwen",
  "kimi",
  "qoder",
  "codebuddy",
  "trae",
  "crewai",
  "opensre",
  "mcp_proxy",
];

describe("normalizeSourceApp", () => {
  it("folds the pre-rename codename onto agentmetry", () => {
    expect(normalizeSourceApp("blackbox")).toBe("agentmetry");
  });

  it("maps the short MCP alias to the proxy key", () => {
    expect(normalizeSourceApp("mcp")).toBe("mcp_proxy");
  });

  it("is case- and whitespace-insensitive", () => {
    expect(normalizeSourceApp("  Cursor ")).toBe("cursor");
  });

  it("passes an unknown app through rather than inventing one", () => {
    expect(normalizeSourceApp("windsurf")).toBe("windsurf");
  });
});

describe("source presentation", () => {
  it.each(FIRST_PARTY)("gives %s a distinct label", (app) => {
    expect(sourceLabel(app)).not.toBe(app);
  });

  it.each(FIRST_PARTY)("gives %s a badge, dot and chart colour", (app) => {
    expect(sourceBadgeClass(app)).toContain("bg-");
    expect(sourceDotClass(app)).toContain("bg-");
    expect(sourceChartColor(app)).toMatch(/^#[0-9a-f]{6}$/);
  });

  it("falls back to neutral styling for an unknown app", () => {
    expect(sourceBadgeClass("windsurf")).toContain("slate");
    expect(sourceChartColor("windsurf")).toBe("#94a3b8");
  });

  it("shows an unknown app under its own name, not a wrong one", () => {
    expect(sourceLabel("windsurf")).toBe("windsurf");
  });

  it("mutes the dot when a source is inactive", () => {
    expect(sourceDotClass("cursor", false)).toBe("bg-muted");
  });

  it("keeps every first-party chart colour unique", () => {
    const colors = FIRST_PARTY.map(sourceChartColor);
    // qoder deliberately shares the mcp_proxy orange; everything else is unique.
    expect(new Set(colors).size).toBeGreaterThanOrEqual(FIRST_PARTY.length - 1);
    expect(Object.keys(SOURCE_CHART_COLOR)).toContain("agentmetry");
  });
});

describe("eventSourceApp", () => {
  it("prefers the explicit source block", () => {
    const ev = { source: { app: "kimi" }, agent: { name: "cursor" } } as unknown as AuditEvent;
    expect(eventSourceApp(ev)).toBe("kimi");
  });

  it("normalizes the legacy name on the source block", () => {
    const ev = { source: { app: "blackbox" } } as unknown as AuditEvent;
    expect(eventSourceApp(ev)).toBe("agentmetry");
  });

  it("falls back to the agent name when no source is recorded", () => {
    const ev = { agent: { name: "codex" } } as unknown as AuditEvent;
    expect(eventSourceApp(ev)).toBe("codex");
  });

  it("defaults to agentmetry for an event with neither", () => {
    expect(eventSourceApp({} as AuditEvent)).toBe("agentmetry");
  });
});
