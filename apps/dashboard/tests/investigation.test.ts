import { describe, expect, it } from "vitest";

import {
  buildHierarchy,
  familyCounts,
  kindLabel,
  layoutHorizontal,
  layoutVertical,
  matchesHighlight,
  signalOf,
  type HierarchyOptions,
} from "@/lib/investigation";
import { citedSet, type SessionNode } from "@/lib/session-tree";

let seq = 0;
const node = (qualified: string, extra: Partial<SessionNode> = {}): SessionNode => {
  seq += 1;
  return {
    id: `n${seq}`,
    event_ids: [`n${seq}`],
    kind: "call",
    timestamp_utc: `2026-10-22T10:${String(seq % 60).padStart(2, "0")}:00+00:00`,
    outcome: "success",
    reason: "",
    app: "cursor",
    adapter: "cursor_hook",
    tool: { qualified, name: qualified.split(".").pop() ?? "", server: "", input_hash: "" },
    approval: null,
    ...extra,
  };
};

const opts = (extra: Partial<HierarchyOptions> = {}): HierarchyOptions => ({
  host: "HOST",
  app: "cursor",
  appLabel: "Cursor",
  adapter: "cursor_hook",
  sessionId: "sess-1",
  hidden: new Set(),
  expanded: new Set(),
  selectedId: null,
  ...extra,
});

describe("signals and labels", () => {
  it("leads with the strongest signal", () => {
    const c = node("shell.run");
    expect(signalOf(c, citedSet(c.event_ids))).toBe("cited");
    expect(signalOf(node("cursor.Read", { kind: "denied" }), citedSet([]))).toBe("refused");
    expect(signalOf(node("cursor.Read", { dlp: { rule_id: "aws_key" } }), citedSet([]))).toBe("dlp");
    expect(signalOf(node("cursor.Read", { outcome: "error" }), citedSet([]))).toBe("error");
    expect(signalOf(node("cursor.Read"), citedSet([]))).toBeNull();
  });

  it("never calls a lifecycle event a tool call", () => {
    expect(kindLabel(node("", { kind: "session_start" }))).toBe("Session started");
    expect(kindLabel(node("", { kind: "hook_remediation" }))).toBe("Hook remediation");
    expect(kindLabel(node("shell.run"))).toBe("Tool call");
  });

  it("highlights only what matches", () => {
    const err = node("shell.run", { outcome: "error" });
    expect(matchesHighlight(err, citedSet([]), "errors")).toBe(true);
    expect(matchesHighlight(err, citedSet([]), "cited")).toBe(false);
    expect(matchesHighlight(err, citedSet([]), null)).toBe(true);
  });
});

describe("category counters", () => {
  it("accounts for every event, session events included, and leads with the cited row", () => {
    const start = node("", { kind: "session_start" });
    const reads = [node("cursor.Read"), node("cursor.Read", { outcome: "error" })];
    const push = node("shell.run");
    const rows = familyCounts([start, ...reads, push], citedSet(push.event_ids));
    expect(rows[0]).toMatchObject({ key: "shell", calls: 1, cited: 1 });
    expect(rows.find((r) => r.key === "files")).toMatchObject({ calls: 2, errors: 1 });
    expect(rows.find((r) => r.key === "session")).toMatchObject({ calls: 1 });
    expect(rows.reduce((n, r) => n + r.calls, 0)).toBe(4);
  });
});

describe("hierarchy", () => {
  const calls = Array.from({ length: 20 }, () => node("shell.run"));
  const cited = citedSet(calls[15].event_ids);

  it("is machine, agent, session, category, then calls", () => {
    const h = buildHierarchy(calls, cited, opts());
    expect(h.slice(0, 4).map((e) => e.kind)).toEqual(["machine", "agent", "session", "family"]);
    expect(h.find((e) => e.kind === "family")?.parent).toBe("session");
    expect(h.filter((e) => e.kind === "call").every((e) => e.parent === "family:shell")).toBe(true);
  });

  it("folds a long category but never the cited call or the selection", () => {
    const h = buildHierarchy(calls, cited, opts({ selectedId: calls[12].id, perFamily: 5 }));
    const shown = h.filter((e) => e.kind === "call").map((e) => e.id);
    expect(shown).toContain(calls[15].id);
    expect(shown).toContain(calls[12].id);
    expect(shown).toHaveLength(5);
    expect(h.find((e) => e.kind === "more")).toMatchObject({ count: 15, parent: "family:shell" });
  });

  it("draws a category whole once it is expanded", () => {
    const h = buildHierarchy(calls, cited, opts({ expanded: new Set(["shell"]) }));
    expect(h.filter((e) => e.kind === "call")).toHaveLength(20);
    expect(h.find((e) => e.kind === "more")).toBeUndefined();
  });

  it("leaves a hidden category out entirely", () => {
    const mixed = [node("shell.run"), node("cursor.Read")];
    const h = buildHierarchy(mixed, citedSet([]), opts({ hidden: new Set(["files"]) }));
    expect(h.some((e) => e.familyKey === "files")).toBe(false);
    expect(h.some((e) => e.familyKey === "shell")).toBe(true);
  });

  it("keeps session events out of the tree; the table counts them", () => {
    const h = buildHierarchy([node("", { kind: "session_end" }), node("shell.run")], citedSet([]), opts());
    expect(h.some((e) => e.familyKey === "session")).toBe(false);
  });
});

describe("layout", () => {
  const h = buildHierarchy([node("shell.run"), node("shell.run"), node("cursor.Read")], citedSet([]), opts());

  it("puts each level in its own column, left to right, parents centred on children", () => {
    const placed = layoutHorizontal(h, 100, 10);
    const x = (kind: string) => new Set(placed.filter((p) => p.entity.kind === kind).map((p) => p.x));
    expect([...x("machine")]).toEqual([0]);
    expect([...x("family")]).toEqual([300]);
    expect([...x("call")]).toEqual([400]);
    const shell = placed.find((p) => p.entity.id === "family:shell")!;
    const kids = placed.filter((p) => p.entity.parent === "family:shell");
    expect(shell.y).toBe(kids.reduce((s, k) => s + k.y, 0) / kids.length);
  });

  it("turns the same tree on its side for the graph", () => {
    const placed = layoutVertical(h, 10, 100);
    expect(placed.find((p) => p.entity.kind === "session")!.y).toBe(200);
    expect(new Set(placed.filter((p) => p.entity.kind === "call").map((p) => p.y))).toEqual(new Set([400]));
  });
});
