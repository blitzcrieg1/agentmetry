import { describe, expect, it } from "vitest";

import {
  accountName,
  accountSourceLabel,
  accountsOfKind,
  ACCOUNT_SECTIONS,
  agentCoverageSentence,
  approvalState,
  countOutside,
  organizationSummary,
  parseApprovedDomains,
  shortOrganization,
  type IdentityAccount,
  type IdentityAgent,
} from "@/lib/identity";

const account = (domain: string, kind: IdentityAccount["kind"] = "corporate"): IdentityAccount => ({
  kind,
  domain,
  organization_ids: [],
  account_id: "",
  user_id: "",
  emails: [],
  sources: [],
  agents: [],
  hosts: [],
  operators: [],
  sessions: 1,
  events: 1,
  detection_count: 0,
  highest_severity: "",
  detections: [],
  first_seen: "",
  last_seen: "",
});

const agent = (state: IdentityAgent["state"], extra: Partial<IdentityAgent> = {}): IdentityAgent => ({
  name: "cursor",
  events: 4,
  events_since_first_report: 4,
  events_with_account: 4,
  state,
  first_reported: "",
  last_seen: "",
  ...extra,
});

describe("approved domains", () => {
  it("reads commas, spaces and new lines, and tidies what people paste", () => {
    expect(parseApprovedDomains("Company.Example, @other.example\n*.third.example  fourth.example.")).toEqual([
      "company.example",
      "other.example",
      "third.example",
      "fourth.example",
    ]);
  });

  it("drops empty entries and duplicates", () => {
    expect(parseApprovedDomains(" , a.example,, A.EXAMPLE ")).toEqual(["a.example"]);
  });

  it("marks nothing against the approved list until one exists", () => {
    expect(approvalState("gmail.com", [])).toBe("unchecked");
  });

  it("approves the domain and its subdomains", () => {
    expect(approvalState("company.example", ["company.example"])).toBe("approved");
    expect(approvalState("dev.company.example", ["company.example"])).toBe("approved");
  });

  it("does not approve a look-alike", () => {
    expect(approvalState("company.example.evil.test", ["company.example"])).toBe("outside");
    expect(approvalState("notcompany.example", ["company.example"])).toBe("outside");
  });

  it("matches an account with no domain on its exact ID", () => {
    expect(approvalState("", ["workspace-1"], "Workspace-1")).toBe("approved");
    expect(approvalState("", ["workspace-1"], "workspace-2")).toBe("outside");
    expect(approvalState("", [], "workspace-1")).toBe("unchecked");
  });

  it("names an account by its most readable claim", () => {
    expect(accountName({ domain: "example.com", account_id: "a", user_id: "" })).toBe("example.com");
    expect(accountName({ domain: "", account_id: "workspace-1", user_id: "" })).toBe("Account workspace-1");
    expect(accountName({ domain: "", account_id: "", user_id: "user-1" })).toBe("User user-1");
    expect(accountName({ domain: "", account_id: "", user_id: "" })).toBe("Organization only");
  });

  it("does not call an organization-only account outside the list", () => {
    expect(approvalState("", ["company.example"])).toBe("no_domain");
  });

  it("counts only accounts outside the list", () => {
    const accounts = [account("company.example"), account("gmail.com"), account("")];
    expect(countOutside(accounts, ["company.example"])).toBe(1);
    expect(countOutside(accounts, [])).toBe(0);
  });
});

describe("account sections", () => {
  it("shows personal accounts first, then corporate", () => {
    expect(ACCOUNT_SECTIONS.map((section) => section.kind)).toEqual(["personal", "corporate", "unclassified"]);
  });

  it("puts each account in the section the API named", () => {
    const accounts = [account("gmail.com", "personal"), account("company.example"), account("", "unclassified")];
    expect(accountsOfKind(accounts, "personal").map((a) => a.domain)).toEqual(["gmail.com"]);
    expect(accountsOfKind(accounts, "corporate").map((a) => a.domain)).toEqual(["company.example"]);
    expect(accountsOfKind(accounts, "unclassified")).toHaveLength(1);
  });
});

describe("agent coverage sentences", () => {
  it("does not blame an agent that has no documented field", () => {
    expect(agentCoverageSentence(agent("no_documented_field"))).toContain("no account field");
  });

  it("gives each silent agent its own reason, not another agent's", () => {
    const cursor = agentCoverageSentence(agent("not_reported", { name: "cursor" }));
    expect(cursor).toContain("Cursor");
    expect(cursor).not.toContain("Codex");
    const codex = agentCoverageSentence(agent("not_reported", { name: "codex" }));
    expect(codex).toContain("session file");
    expect(codex).not.toContain("Cursor");
    const claude = agentCoverageSentence(agent("not_reported", { name: "claude" }));
    expect(claude).toContain("API key");
    expect(claude).not.toContain("Cursor");
  });

  it("says plainly when an agent has not been checked", () => {
    const sentence = agentCoverageSentence(agent("not_reported", { name: "zcode" }));
    expect(sentence).toContain("no safe place");
    expect(sentence).not.toMatch(/Cursor|Claude|Codex/);
  });

  it("gives the numbers for an agent that partly reports", () => {
    const sentence = agentCoverageSentence(
      agent("partial", { events_with_account: 3, events_since_first_report: 5 }),
    );
    expect(sentence).toContain("3 of 5");
  });

  it("says an old gap is over without hiding it", () => {
    const sentence = agentCoverageSentence(
      agent("reported", { events_with_account: 137, events_since_first_report: 160 }),
    );
    expect(sentence).toBe("Reporting now. 23 earlier events since the first report had none.");
  });

  it("says plainly when every event carried an account", () => {
    expect(agentCoverageSentence(agent("reported"))).toBe("Every event since the first report carried an account.");
  });
});

describe("account labels", () => {
  it("says local_config is the machine's last sign-in, not proof of who acted", () => {
    expect(accountSourceLabel("local_config")).toBe("Last account signed in on this machine");
  });

  it("passes through a source it does not know", () => {
    expect(accountSourceLabel("something_new")).toBe("something_new");
  });

  it("summarises organizations under an account name", () => {
    expect(organizationSummary([])).toBe("");
    expect(organizationSummary(["org-1"])).toBe("org org-1");
    expect(organizationSummary(["org-1", "org-2"])).toBe("2 organizations");
  });

  it("shortens only long organization ids", () => {
    expect(shortOrganization("org-123")).toBe("org-123");
    expect(shortOrganization("00000000-1111-2222-3333-444444444444")).toBe("00000000…");
  });
});
