import { describe, expect, it } from "vitest";

import {
  agentsByAttention,
  dlpModeSentence,
  listingSentence,
  mcpFindingLabel,
  policyModeSentence,
  type McpServerRow,
} from "@/lib/machine";

const row = (listing: McpServerRow["listing"], extra: Partial<McpServerRow> = {}): McpServerRow => ({
  agent: "cursor",
  name: "mail",
  scope: "user",
  transport: "stdio",
  launcher: "npx",
  package: "some-server",
  url_host: "",
  findings: [],
  fingerprint: "abc",
  observed: listing !== "not_observed",
  listing,
  observed_at: "",
  tool_count: 3,
  ...extra,
});

describe("machine view labels", () => {
  it("puts an unhooked agent ahead of one that is recorded", () => {
    const ordered = agentsByAttention([
      { name: "claude", state: "covered" },
      { name: "cursor", state: "uncovered" },
      { name: "codex", state: "absent" },
    ]);
    expect(ordered.map((agent) => agent.name)).toEqual(["cursor", "claude", "codex"]);
  });

  it("describes a listing change without claiming the config file stayed still", () => {
    expect(listingSentence(row("changed"))).toMatch(/cannot see whether the config file changed/);
    expect(listingSentence(row("not_observed"))).toMatch(/unknown/);
    expect(mcpFindingLabel("unpinned_fetch")).toMatch(/Unpinned/);
    expect(mcpFindingLabel("made_up")).toBe("made_up");
  });

  it("says what log mode does", () => {
    expect(policyModeSentence("log")).toMatch(/still runs/);
    expect(policyModeSentence("block")).toMatch(/before it runs/);
    expect(dlpModeSentence("log", 21)).toBe(
      "DLP is in log mode, 21 rules. A match is recorded and the tool still runs.",
    );
  });
});
