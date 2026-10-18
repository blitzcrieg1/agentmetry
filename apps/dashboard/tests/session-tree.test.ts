import { describe, expect, it } from "vitest";

import {
  approvalSentence,
  buildBranches,
  citedSet,
  foldBranch,
  shortTool,
  timelinePct,
  toolFamily,
  type SessionNode,
} from "@/lib/session-tree";

let seq = 0;
const node = (qualified: string, extra: Partial<SessionNode> = {}): SessionNode => {
  seq += 1;
  return {
    id: `n${seq}`,
    event_ids: [`n${seq}`],
    kind: "call",
    timestamp_utc: `2026-10-15T16:${String(seq % 60).padStart(2, "0")}:00+00:00`,
    outcome: "success",
    reason: "",
    app: "cursor",
    adapter: "cursor_hook",
    tool: { qualified, name: qualified.split(".").pop() ?? "", server: "", input_hash: "" },
    approval: null,
    ...extra,
  };
};

describe("tool families", () => {
  it("puts every agent's shell under one branch", () => {
    expect(toolFamily(node("shell.run")).key).toBe("shell");
    expect(toolFamily(node("cursor.Shell")).key).toBe("shell");
    expect(toolFamily(node("Bash", { app: "claude" })).key).toBe("shell");
    expect(toolFamily(node("PowerShell", { app: "claude" })).key).toBe("shell");
    expect(toolFamily(node("antigravity.run_command", { app: "antigravity" })).key).toBe("shell");
  });

  it("gives each MCP server its own branch, named after the server", () => {
    const fam = toolFamily(node("mcp__Claude_Browser__navigate", { app: "claude" }));
    expect(fam).toEqual({ key: "mcp:Claude_Browser", label: "MCP: Claude_Browser", family: "mcp" });
    expect(shortTool(node("mcp__Claude_Browser__navigate", { app: "claude" }))).toBe("navigate");
  });

  it("sorts files, web and subagents, and leaves the unknown as other", () => {
    expect(toolFamily(node("cursor.Read")).key).toBe("files");
    expect(toolFamily(node("antigravity.view_file", { app: "antigravity" })).key).toBe("files");
    expect(toolFamily(node("WebFetch", { app: "claude" })).key).toBe("web");
    expect(toolFamily(node("claude.subagent.explore", { kind: "subagent_start", app: "claude" })).key).toBe("subagents");
    expect(toolFamily(node("TaskUpdate", { app: "claude" })).key).toBe("other");
  });
});

describe("branches", () => {
  it("leads with the branch the detection cites, and keeps lifecycle markers out", () => {
    const read = Array.from({ length: 5 }, () => node("cursor.Read"));
    const push = node("shell.run");
    const start = node("", { kind: "session_start" });
    const branches = buildBranches([start, ...read, push], citedSet(push.event_ids));
    expect(branches.map((b) => b.key)).toEqual(["shell", "files"]);
    expect(branches[0].cited).toBe(1);
  });

  it("counts a node as cited when the detection cites the ask folded into it", () => {
    const call = node("shell.run", { event_ids: ["ask-1", "answer-1", "call-1"] });
    const [branch] = buildBranches([call], citedSet(["ask-1"]));
    expect(branch.cited).toBe(1);
  });
});

describe("folding", () => {
  const calls = Array.from({ length: 20 }, () => node("shell.run"));
  const cited = citedSet(calls[10].event_ids);
  const [branch] = buildBranches(calls, cited);

  it("shows the cited call with two neighbours each side and folds the rest", () => {
    const rows = foldBranch(branch, cited, new Set());
    expect(rows.map((r) => r.type)).toEqual(["fold", "node", "node", "node", "node", "node", "fold"]);
    expect(rows[0]).toMatchObject({ type: "fold", count: 8 });
    expect(rows[3]).toMatchObject({ type: "node", cited: true });
    expect(rows[6]).toMatchObject({ type: "fold", count: 7 });
  });

  it("opens one run when it is expanded, and the whole branch with the star key", () => {
    const first = foldBranch(branch, cited, new Set())[0];
    expect(first.type).toBe("fold");
    const opened = foldBranch(branch, cited, new Set([first.type === "fold" ? first.id : ""]));
    expect(opened.filter((r) => r.type === "node")).toHaveLength(13);
    expect(foldBranch(branch, cited, new Set([`${branch.key}:*`]))).toHaveLength(20);
  });

  it("never folds away a denial or a policy match", () => {
    const quiet = Array.from({ length: 10 }, () => node("cursor.Read"));
    quiet[4] = node("cursor.Read", { kind: "denied", approval: "denied" });
    quiet[7] = node("cursor.Read", { tool_policy: { rule_id: "block_shell_rm", blocked: true } });
    const [b] = buildBranches(quiet, citedSet([]));
    const shown = foldBranch(b, citedSet([]), new Set()).filter((r) => r.type === "node");
    expect(shown).toHaveLength(2);
  });

  it("shows a small branch whole", () => {
    const few = [node("WebFetch", { app: "claude" }), node("WebSearch", { app: "claude" })];
    const [b] = buildBranches(few, citedSet([]));
    expect(foldBranch(b, citedSet([]), new Set())).toHaveLength(2);
  });
});

describe("timeline and approvals", () => {
  it("places a moment on the session's span and clamps bad input", () => {
    expect(timelinePct("2026-10-15T16:30:00Z", "2026-10-15T16:00:00Z", "2026-10-15T17:00:00Z")).toBe(50);
    expect(timelinePct("nope", "2026-10-15T16:00:00Z", "2026-10-15T17:00:00Z")).toBe(0);
    expect(timelinePct("2026-10-15T18:00:00Z", "2026-10-15T16:00:00Z", "2026-10-15T17:00:00Z")).toBe(100);
  });

  it("never calls an inferred approval a human approval", () => {
    expect(approvalSentence(node("shell.run", { approval: "inferred" }))).toMatch(/inferred/);
    expect(approvalSentence(node("shell.run", { approval: "denied" }))).toMatch(/did not run/);
    expect(approvalSentence(node("shell.run"))).toBeNull();
  });

  it("does not call an ask the session outlived a refusal, nor an unanswered ask that ran unrun", () => {
    expect(approvalSentence(node("cursor.Shell", { kind: "ask", approval: "expired" }))).toMatch(/nobody refused it/);
    expect(approvalSentence(node("shell.run", { kind: "call", approval: "asked" }))).toMatch(/the call ran/);
    expect(approvalSentence(node("cursor.Shell", { kind: "ask", approval: "asked" }))).toMatch(/no call were recorded/);
  });

  it("does not flag a call that merely failed", () => {
    const [b] = buildBranches([node("shell.run", { outcome: "error" })], citedSet([]));
    expect(b.flagged).toBe(0);
  });
});
