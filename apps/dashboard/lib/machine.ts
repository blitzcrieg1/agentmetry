/** Labels for GET /api/v1/audit/machine. The API sends codes, not sentences. */

export type AgentState = "covered" | "uncovered" | "absent" | "unknown";

export type MachineAgent = { name: string; state: AgentState };

export type PostureFinding = {
  agent: string;
  scope: string;
  setting: string;
  value: string;
  severity: string;
  why: string;
};

export type McpServerRow = {
  agent: string;
  name: string;
  scope: string;
  transport: string;
  launcher: string;
  package: string;
  url_host: string;
  findings: string[];
  fingerprint: string;
  observed: boolean;
  listing: "not_observed" | "baseline" | "changed" | "not_comparable";
  observed_at: string;
  tool_count: number | null;
};

export type PolicyRule = {
  id: string;
  action: string;
  description: string;
  tools: number;
  matches_command: boolean;
};

export type MachineSnapshot = {
  host_id: string;
  profile: "user" | "service";
  agents: MachineAgent[];
  posture: {
    findings: PostureFinding[];
    counts: { high: number; medium: number; low: number };
    unreadable: number;
    not_checked: { agent: string; why: string }[];
  };
  mcp: {
    config_digest: string;
    schema_digest: string;
    observed_servers: number;
    servers: McpServerRow[];
  };
  policy: {
    mode: string;
    default: string;
    rules: PolicyRule[];
    ask_reaches: { agent: string; hook: string }[];
    dlp_mode: string;
    dlp_rules: number;
  };
};

export const AGENT_STATE_LABEL: Record<AgentState, string> = {
  covered: "Recorded",
  uncovered: "Not recorded",
  absent: "Not installed",
  unknown: "Unknown",
};

const STATE_RANK: Record<AgentState, number> = {
  uncovered: 0,
  unknown: 1,
  covered: 2,
  absent: 3,
};

export function agentsByAttention(agents: MachineAgent[]): MachineAgent[] {
  return [...agents].sort(
    (a, b) => STATE_RANK[a.state] - STATE_RANK[b.state] || a.name.localeCompare(b.name),
  );
}

export const MCP_FINDING_LABEL: Record<string, string> = {
  no_command: "No command, so the agent cannot start it",
  unpinned_fetch: "Unpinned. The package is fetched again on every launch",
  auto_confirm: "An auto-confirm flag skips the first-run prompt",
  plaintext_http: "The server URL is http, not https",
};

export function mcpFindingLabel(code: string): string {
  return MCP_FINDING_LABEL[code] ?? code;
}

export function listingSentence(row: McpServerRow): string {
  if (row.listing === "not_observed") {
    return "Not listed through the proxy. The tools the model was handed are unknown.";
  }
  if (row.listing === "not_comparable") {
    return "A listing is stored, and it was hashed by an older version, so it cannot be compared with today.";
  }
  if (row.listing === "changed") {
    return "The last tools/list differs from the listing before it. This page cannot see whether the config file changed at the same time.";
  }
  const count = row.tool_count == null ? "" : `${row.tool_count} tools. `;
  return `${count}Listed once, or the listing has not differed from the one before it.`;
}

export function policyModeSentence(mode: string): string {
  if (mode === "block") return "Block mode. A deny stops the tool before it runs.";
  if (mode === "disable") return "Tool policy is off.";
  return "Log mode. A matching rule is recorded and the tool still runs.";
}

export function dlpModeSentence(mode: string, rules: number): string {
  const noun = rules === 1 ? "rule" : "rules";
  if (mode === "block") return `DLP is in block mode, ${rules} ${noun}. A match stops the tool before it runs.`;
  if (mode === "disable") return "DLP is off.";
  return `DLP is in log mode, ${rules} ${noun}. A match is recorded and the tool still runs.`;
}
