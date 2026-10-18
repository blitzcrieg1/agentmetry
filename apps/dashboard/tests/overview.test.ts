import { describe, expect, it } from "vitest";

import type { Detection } from "@/components/flight-recorder-panel";
import type { DogfoodReport } from "@/lib/dogfood";
import type { MachineSnapshot } from "@/lib/machine";
import { attentionItems, sourceBars, techniqueCounts } from "@/lib/overview";

const det = (severity: Detection["severity"], title: string, techniques: string[] = []): Detection => ({
  rule_id: title.toLowerCase().replace(/\s+/g, "-"),
  title,
  severity,
  summary: "",
  correlation_id: "s",
  tactic_ids: [],
  technique_ids: techniques,
  event_ids: [],
  first_seen_utc: "",
  last_seen_utc: "",
});

const machine = (extra: Partial<MachineSnapshot> = {}): MachineSnapshot => ({
  host_id: "h",
  profile: "user",
  agents: [{ name: "cursor", state: "covered" }],
  posture: { findings: [], counts: { high: 0, medium: 0, low: 0 }, unreadable: 0, not_checked: [] },
  mcp: { config_digest: "", schema_digest: "", observed_servers: 0, servers: [] },
  policy: { mode: "log", default: "allow", rules: [], ask_reaches: [], dlp_mode: "log", dlp_rules: 21 },
  ...extra,
});

const gate = (extra: Partial<DogfoodReport> = {}): DogfoodReport => ({
  started: "2026-08-30",
  consecutive_green: 0,
  required: 4,
  passed: false,
  chain_ok: true,
  chain_message: "ok",
  spooled: 0,
  weeks: [
    { index: 6, start: "", end: "", events: 1, active_days: 7, sessions: 1, detections: 1, untriaged: 1, complete: true, verdict: "RED", reasons: [] },
    { index: 7, start: "", end: "", events: 1, active_days: 7, sessions: 1, detections: 9, untriaged: 7, complete: true, verdict: "RED", reasons: [] },
  ],
  ...extra,
});

describe("needs attention", () => {
  it("puts an unverified trail above everything else", () => {
    const items = attentionItems({
      untriaged: [det("critical", "Credential access followed by network egress")],
      stats: null,
      machine: null,
      dogfood: gate({ chain_ok: false, chain_message: "line 12 does not chain" }),
      status: null,
    });
    expect(items[0]).toMatchObject({ id: "chain", severity: "critical", body: "line 12 does not chain" });
    expect(items[1].id).toBe("critical");
  });

  it("names the untriaged findings and counts the gate's red weeks", () => {
    const items = attentionItems({
      untriaged: [det("critical", "A"), det("critical", "A"), det("high", "B")],
      stats: null,
      machine: null,
      dogfood: gate(),
      status: null,
    });
    expect(items.find((i) => i.id === "critical")?.title).toBe("2 critical detections with no decision");
    expect(items.find((i) => i.id === "critical")?.body).toBe("A");
    expect(items.find((i) => i.id === "gate")?.body).toBe(
      "Weeks 6 and 7 are red on 8 detections nobody has dispositioned. Triaging them turns them green.",
    );
  });

  it("says log mode let matched calls run only when there were matches", () => {
    const quiet = attentionItems({ untriaged: [], stats: { tool_policy_hits: 0, dlp_matches: 0 }, machine: machine(), dogfood: null, status: null });
    expect(quiet.find((i) => i.id === "logmode")).toBeUndefined();
    const loud = attentionItems({ untriaged: [], stats: { tool_policy_hits: 14, dlp_matches: 20 }, machine: machine(), dogfood: null, status: null });
    expect(loud.find((i) => i.id === "logmode")?.body).toBe(
      "14 tool policy matches and 20 DLP matches in 7 days were recorded, and the calls still ran.",
    );
    const blocking = attentionItems({
      untriaged: [],
      stats: { tool_policy_hits: 14, dlp_matches: 20 },
      machine: machine({ policy: { ...machine().policy, mode: "block" } }),
      dogfood: null,
      status: null,
    });
    expect(blocking.find((i) => i.id === "logmode")).toBeUndefined();
  });

  it("flags an unhooked agent, a spool backlog, an unseen MCP server and an unchecked agent", () => {
    const items = attentionItems({
      untriaged: [],
      stats: null,
      machine: machine({
        agents: [{ name: "codex", state: "uncovered" }],
        mcp: {
          config_digest: "",
          schema_digest: "",
          observed_servers: 0,
          servers: [{ agent: "cursor", name: "hyperframes", scope: "user", transport: "http", launcher: "", package: "", url_host: "", findings: [], fingerprint: "", observed: false, listing: "not_observed", observed_at: "", tool_count: null }],
        },
        posture: { findings: [], counts: { high: 0, medium: 0, low: 0 }, unreadable: 0, not_checked: [{ agent: "cursor", why: "auto-run lives in Cursor's editor state database" }] },
      }),
      dogfood: null,
      status: { spool_pending: 3 },
    });
    expect(items.map((i) => i.id)).toEqual(["spool", "uncovered", "mcp", "nc-cursor"]);
    expect(items.find((i) => i.id === "mcp")?.body).toMatch(/^hyperframes \(Cursor\)/);
    expect(items.find((i) => i.id === "nc-cursor")?.body).toBe("Auto-run lives in Cursor's editor state database.");
  });

  it("is empty when nothing needs a person", () => {
    expect(attentionItems({ untriaged: [], stats: {}, machine: machine(), dogfood: gate({ weeks: [] }), status: { spool_pending: 0 } })).toEqual([]);
  });
});

describe("overview charts", () => {
  it("scales source bars to the busiest agent and drops empty ones", () => {
    expect(sourceBars({ cursor: 4900, claude: 2450, zcode: 0 })).toEqual([
      { app: "cursor", n: 4900, pct: 100 },
      { app: "claude", n: 2450, pct: 50 },
    ]);
  });

  it("counts techniques across detections, most frequent first", () => {
    expect(techniqueCounts([det("high", "a", ["T1059"]), det("high", "b", ["T1059", "T1552.001"])])).toEqual([
      { id: "T1059", n: 2 },
      { id: "T1552.001", n: 1 },
    ]);
  });
});
