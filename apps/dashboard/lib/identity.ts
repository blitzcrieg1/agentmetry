/** Labels for GET /api/v1/audit/identity. The API sends codes, not sentences. */

export type IdentityDetection = {
  rule_id: string;
  title: string;
  severity: string;
  correlation_id: string;
  agent: string;
  timestamp_utc: string;
};

export type AccountKind = "personal" | "corporate" | "unclassified";

export type IdentityAccount = {
  kind: AccountKind;
  domain: string;
  organization_ids: string[];
  account_id: string;
  user_id: string;
  emails: string[];
  sources: string[];
  agents: string[];
  hosts: string[];
  operators: string[];
  sessions: number;
  events: number;
  detection_count: number;
  highest_severity: string;
  detections: IdentityDetection[];
  first_seen: string;
  last_seen: string;
};

export type AgentCoverageState = "reported" | "partial" | "not_reported" | "no_documented_field";

export type IdentityAgent = {
  name: string;
  events: number;
  events_since_first_report: number;
  events_with_account: number;
  state: AgentCoverageState;
  first_reported: string;
  last_seen: string;
};

export type IdentitySnapshot = {
  enabled: boolean;
  window_days: number;
  truncated: boolean;
  accounts: IdentityAccount[];
  counts: Record<AccountKind, number>;
  agents: IdentityAgent[];
  sessions: number;
  sessions_without_account: number;
  detections_without_account: number;
};

export type ApprovalState = "unchecked" | "approved" | "outside" | "no_domain";

/** The order the page shows them in, and what each section says about itself. */
export const ACCOUNT_SECTIONS: { kind: AccountKind; title: string; note: string; empty: string }[] = [
  {
    kind: "personal",
    title: "Personal accounts",
    note: "The domain is a known public email provider, so this account is outside any company tenant.",
    empty: "No personal account reported in this window.",
  },
  {
    kind: "corporate",
    title: "Corporate accounts",
    note: "The domain is not a known public provider. That usually means a company, but somebody's own domain reads the same way.",
    empty: "No corporate account reported in this window.",
  },
  {
    kind: "unclassified",
    title: "Accounts with no domain",
    note: "These report only an ID, so they cannot be called personal or corporate. Add an approved ID below to check them.",
    empty: "",
  },
];

export function accountsOfKind(accounts: IdentityAccount[], kind: AccountKind): IdentityAccount[] {
  return accounts.filter((account) => account.kind === kind);
}

/** Accepts commas, spaces or new lines, and forgives a leading `@` or `*.`. */
export function parseApprovedDomains(text: string): string[] {
  const domains = text
    .split(/[\s,;]+/)
    .map((part) => part.trim().toLowerCase().replace(/^@/, "").replace(/^\*\./, "").replace(/\.$/, ""))
    .filter(Boolean);
  return [...new Set(domains)];
}

/**
 * A subdomain of an approved domain is approved. A look-alike is not. An account
 * with no domain, such as Codex's, is matched on its exact account ID.
 */
export function approvalState(domain: string, approved: string[], accountId = ""): ApprovalState {
  if (!domain && !accountId) return "no_domain";
  if (approved.length === 0) return "unchecked";
  if (!domain) return approved.includes(accountId.toLowerCase()) ? "approved" : "outside";
  const value = domain.toLowerCase();
  return approved.some((item) => value === item || value.endsWith(`.${item}`)) ? "approved" : "outside";
}

export const APPROVAL_LABEL: Record<ApprovalState, string> = {
  unchecked: "No list set",
  approved: "Approved",
  outside: "Outside list",
  no_domain: "Not listable",
};

export const AGENT_COVERAGE_LABEL: Record<AgentCoverageState, string> = {
  reported: "Reporting",
  partial: "Partly reporting",
  not_reported: "Unknown",
  no_documented_field: "Unknown",
};

const NOT_REPORTED_SENTENCE: Record<string, string> = {
  cursor: "No account in this window. Cursor sends one only when it knows the signed-in user.",
  claude: "No account in this window. The lookup is skipped when an API key, token, cloud provider or other endpoint is in use.",
  codex: "No account ID in this window. Codex's IDs come from its session file, which may not exist yet on a session's first event. Events from before this was added have none.",
  antigravity: "No account in this window. Antigravity's comes from the last sign-in on this machine, in a file that can change between versions. Events from before this was added have none.",
};

export function agentCoverageSentence(agent: IdentityAgent): string {
  if (agent.state === "no_documented_field") {
    return "This agent's documented hook input has no account field, so its account stays unknown.";
  }
  if (agent.state === "not_reported") {
    return NOT_REPORTED_SENTENCE[agent.name] ?? "Agentmetry records this agent, but no safe place that names its account has been found, so its account stays unknown.";
  }
  if (agent.state === "partial") {
    return `The newest event carried no account. ${agent.events_with_account} of ${agent.events_since_first_report} events since the first report did.`;
  }
  const gap = agent.events_since_first_report - agent.events_with_account;
  if (gap > 0) {
    return `Reporting now. ${gap} earlier ${gap === 1 ? "event" : "events"} since the first report had none.`;
  }
  return "Every event since the first report carried an account.";
}

const SOURCE_LABEL: Record<string, string> = {
  hook_payload: "Sent by the agent's hook",
  otel: "Sent in the agent's telemetry",
  local_config: "Last account signed in on this machine",
  session_meta: "Read from the agent's session file",
};

export function accountSourceLabel(source: string): string {
  return SOURCE_LABEL[source] ?? source;
}

/** Enough to tell two organizations apart without filling the table. */
export function shortOrganization(id: string): string {
  return id.length > 13 ? `${id.slice(0, 8)}…` : id;
}

export function accountKey(
  account: Pick<IdentityAccount, "domain" | "organization_ids" | "account_id" | "user_id">,
): string {
  if (account.domain) return `domain:${account.domain}`;
  return `id:${account.organization_ids.join(",")}|${account.account_id}|${account.user_id}`;
}

/** The line under an account's name, when it reports one or more organizations. */
export function organizationSummary(ids: string[]): string {
  if (ids.length === 0) return "";
  return ids.length === 1 ? `org ${shortOrganization(ids[0])}` : `${ids.length} organizations`;
}

/** What the table calls an account, from the most to the least readable claim. */
export function accountName(
  account: Pick<IdentityAccount, "domain" | "account_id" | "user_id">,
): string {
  if (account.domain) return account.domain;
  if (account.account_id) return `Account ${shortOrganization(account.account_id)}`;
  if (account.user_id) return `User ${shortOrganization(account.user_id)}`;
  return "Organization only";
}

export function countOutside(accounts: IdentityAccount[], approved: string[]): number {
  return accounts.filter((account) => approvalState(account.domain, approved, account.account_id) === "outside").length;
}

/** Times are ISO-8601 UTC, shown in the viewer's own zone. */
export function shortTime(value: string): string {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
