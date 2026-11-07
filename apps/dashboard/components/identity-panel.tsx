"use client";

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Info, RefreshCw, UserSearch } from "lucide-react";
import { apiHeaders } from "@/lib/api";
import { sourceLabel } from "@/lib/audit-source";
import { AgentTile } from "@/components/ui/agent-mark";
import { EmptyState, Segmented, SeverityBadge } from "@/components/ui/kit";
import {
  ACCOUNT_SECTIONS,
  APPROVAL_LABEL,
  AGENT_COVERAGE_LABEL,
  accountKey,
  accountName,
  accountSourceLabel,
  accountsOfKind,
  agentCoverageSentence,
  approvalState,
  countOutside,
  organizationSummary,
  parseApprovedDomains,
  shortTime,
  type ApprovalState,
  type IdentityAccount,
  type IdentityAgent,
  type IdentitySnapshot,
} from "@/lib/identity";
import { ORCHESTRATOR_URL } from "@/lib/utils";

const STORAGE_KEY = "agentmetry.identity.approvedDomains";
const DEMO_APPROVED = "company.example, demo-workspace-0001";

type Window = "7" | "30" | "90";
const WINDOWS: { value: Window; label: string }[] = [
  { value: "7", label: "7 days" },
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
];

function readStoredList(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function storeList(value: string) {
  try {
    window.localStorage.setItem(STORAGE_KEY, value);
  } catch {
    /* A convenience for this browser. The page works without it. */
  }
}

function Stat({ label, value, detail, tone = "text-foreground" }: { label: string; value: string; detail: string; tone?: string }) {
  return (
    <div className="panel px-4 py-3">
      <p className="eyebrow">{label}</p>
      <p className={`mt-1 font-mono text-[22px] font-medium leading-none ${tone}`}>{value}</p>
      <p className="mt-1.5 text-[12px] text-muted-foreground">{detail}</p>
    </div>
  );
}

function ApprovalPill({ state }: { state: ApprovalState }) {
  const tone =
    state === "outside"
      ? "bg-danger/10 text-danger"
      : state === "approved"
        ? "bg-muted text-foreground"
        : "bg-muted text-subtle";
  return (
    <span className={`inline-flex items-center whitespace-nowrap rounded-sm px-2 py-0.5 font-mono text-[12px] font-medium ${tone}`}>
      {APPROVAL_LABEL[state]}
    </span>
  );
}

function CoveragePill({ agent }: { agent: IdentityAgent }) {
  const tone =
    agent.state === "reported"
      ? "bg-muted text-foreground"
      : agent.state === "partial"
        ? "bg-caution/15 text-caution"
        : "bg-caution/15 text-caution";
  return (
    <span className={`inline-flex items-center whitespace-nowrap rounded-sm px-2 py-0.5 font-mono text-[12px] font-medium ${tone}`}>
      {AGENT_COVERAGE_LABEL[agent.state]}
    </span>
  );
}

function AccountDetail({
  account,
  onOpenDetection,
}: {
  account: IdentityAccount;
  onOpenDetection: (correlationId: string, ruleId: string) => void;
}) {
  return (
    <div className="grid gap-4 border-t border-border bg-muted/30 px-4 py-4 md:grid-cols-2">
      <div className="min-w-0 space-y-3 text-[13px]">
        <div>
          <p className="eyebrow mb-1">How it is known</p>
          <ul className="space-y-0.5">
            {account.sources.length ? (
              account.sources.map((source) => <li key={source}>{accountSourceLabel(source)}</li>)
            ) : (
              <li className="text-muted-foreground">Not stated</li>
            )}
          </ul>
        </div>
        {account.emails.length ? (
          <div>
            <p className="eyebrow mb-1">Email addresses</p>
            <ul className="space-y-0.5 break-all font-mono text-[12px]">
              {account.emails.map((email) => (
                <li key={email}>{email}</li>
              ))}
            </ul>
          </div>
        ) : null}
        {account.organization_ids.length ? (
          <div>
            <p className="eyebrow mb-1">{account.organization_ids.length === 1 ? "Organization ID" : "Organization IDs"}</p>
            <ul className="space-y-0.5 break-all font-mono text-[12px]">
              {account.organization_ids.map((id) => (
                <li key={id}>{id}</li>
              ))}
            </ul>
          </div>
        ) : null}
        {account.account_id ? (
          <div>
            <p className="eyebrow mb-1">Account ID</p>
            <p className="break-all font-mono text-[12px]">{account.account_id}</p>
          </div>
        ) : null}
        {account.user_id ? (
          <div>
            <p className="eyebrow mb-1">User ID</p>
            <p className="break-all font-mono text-[12px]">{account.user_id}</p>
          </div>
        ) : null}
        <div>
          <p className="eyebrow mb-1">Operating system accounts</p>
          <p className="break-words font-mono text-[12px]">{account.operators.join(", ") || "None recorded"}</p>
        </div>
        <div>
          <p className="eyebrow mb-1">Hosts</p>
          <p className="break-words font-mono text-[12px]">{account.hosts.join(", ") || "None recorded"}</p>
        </div>
        <div>
          <p className="eyebrow mb-1">Seen</p>
          <p className="text-[12px] text-muted-foreground">
            {shortTime(account.first_seen)} to {shortTime(account.last_seen)}
          </p>
        </div>
      </div>
      <div className="min-w-0">
        <p className="eyebrow mb-1">Detections on this account</p>
        {account.detections.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">None in this window.</p>
        ) : (
          <ul className="space-y-1">
            {account.detections.map((detection) => (
              <li key={`${detection.correlation_id}:${detection.rule_id}:${detection.timestamp_utc}`}>
                <button
                  type="button"
                  onClick={() => onOpenDetection(detection.correlation_id, detection.rule_id)}
                  className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-[13px] transition-colors hover:bg-muted"
                >
                  <SeverityBadge severity={detection.severity} />
                  <span className="min-w-0 flex-1 truncate">{detection.title || detection.rule_id}</span>
                  <span className="shrink-0 text-[12px] text-muted-foreground">{shortTime(detection.timestamp_utc)}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {account.detection_count > account.detections.length ? (
          <p className="mt-1 px-2 text-[12px] text-muted-foreground">
            Showing the newest {account.detections.length} of {account.detection_count}.
          </p>
        ) : null}
      </div>
    </div>
  );
}

function AccountsTable({
  accounts,
  approved,
  onOpenDetection,
}: {
  accounts: IdentityAccount[];
  approved: string[];
  onOpenDetection: (correlationId: string, ruleId: string) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-left text-[13px]">
        <thead>
          <tr className="border-b border-border text-[12px] text-muted-foreground">
            <th className="px-4 py-2 font-medium">Account</th>
            <th className="px-3 py-2 font-medium">List</th>
            <th className="px-3 py-2 font-medium">Agents</th>
            <th className="px-3 py-2 text-right font-medium">Sessions</th>
            <th className="px-3 py-2 font-medium">Detections</th>
            <th className="px-3 py-2 font-medium">Last seen</th>
          </tr>
        </thead>
        <tbody>
          {accounts.map((account) => {
            const key = accountKey(account);
            const isOpen = open === key;
            const name = accountName(account);
            return (
              <Fragment key={key}>
                <tr className="border-b border-border/60 align-middle">
                  <td className="px-4 py-2.5">
                    <button
                      type="button"
                      aria-expanded={isOpen}
                      aria-label={`${isOpen ? "Hide" : "Show"} details for ${name}`}
                      onClick={() => setOpen(isOpen ? null : key)}
                      className="flex items-center gap-1.5 text-left font-mono text-[13px] font-medium hover:text-signal"
                    >
                      {isOpen ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
                      <span className="break-all">{name}</span>
                    </button>
                    {account.organization_ids.length ? (
                      <p className="ml-5 font-mono text-[12px] text-muted-foreground">
                        {organizationSummary(account.organization_ids)}
                      </p>
                    ) : null}
                  </td>
                  <td className="px-3 py-2.5">
                    <ApprovalPill state={approvalState(account.domain, approved, account.account_id)} />
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                      {account.agents.map((agent) => (
                        <span key={agent} className="inline-flex items-center gap-1.5 whitespace-nowrap">
                          <AgentTile app={agent} size="sm" />
                          {sourceLabel(agent)}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono">{account.sessions}</td>
                  <td className="px-3 py-2.5">
                    {account.detection_count ? (
                      <span className="flex items-center gap-2">
                        <SeverityBadge severity={account.highest_severity} />
                        <span className="font-mono">{account.detection_count}</span>
                      </span>
                    ) : (
                      <span className="text-muted-foreground">None</span>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-[12px] text-muted-foreground">{shortTime(account.last_seen)}</td>
                </tr>
                {isOpen ? (
                  <tr className="border-b border-border/60">
                    <td colSpan={6} className="p-0">
                      <AccountDetail account={account} onOpenDetection={onOpenDetection} />
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function CoverageList({ agents }: { agents: IdentityAgent[] }) {
  return (
    <ul className="divide-y divide-border/60">
      {agents.map((agent) => (
        <li key={agent.name} className="flex items-start gap-3 px-4 py-3">
          <AgentTile app={agent.name} size="sm" />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[13px] font-medium">{sourceLabel(agent.name)}</span>
              <CoveragePill agent={agent} />
            </div>
            <p className="mt-1 text-[12px] leading-relaxed text-muted-foreground">{agentCoverageSentence(agent)}</p>
          </div>
        </li>
      ))}
    </ul>
  );
}

export function IdentityPanel({
  demo = false,
  onOpenDetection,
}: {
  demo?: boolean;
  onOpenDetection: (correlationId: string, ruleId: string) => void;
}) {
  const [data, setData] = useState<IdentitySnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState<Window>("30");
  const [listText, setListText] = useState("");

  useEffect(() => {
    const stored = readStoredList();
    setListText(stored ?? (demo ? DEMO_APPROVED : ""));
  }, [demo]);

  const approved = useMemo(() => parseApprovedDomains(listText), [listText]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${ORCHESTRATOR_URL}/api/v1/audit/identity?days=${days}`, {
        headers: apiHeaders(),
        credentials: "include",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData((await res.json()) as IdentitySnapshot);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not read the trail");
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => {
    void load();
  }, [load]);

  const accounts = data?.accounts ?? [];
  const agents = data?.agents ?? [];
  const outside = countOutside(accounts, approved);
  const unknownAgents = agents.filter((agent) => agent.state === "not_reported" || agent.state === "no_documented_field").length;

  if (loading && !data) {
    return <EmptyState>Reading the trail…</EmptyState>;
  }
  if (error && !data) {
    return <EmptyState>Could not read the trail: {error}</EmptyState>;
  }
  if (data && !data.enabled) {
    return <EmptyState>Audit export is off, so there is no trail to read.</EmptyState>;
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-y-auto pb-4">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2">
        <Segmented label="Time window" items={WINDOWS} value={days} onChange={setDays} />
        <button
          type="button"
          onClick={() => void load()}
          className="inline-flex h-8 items-center gap-1.5 rounded-sm border border-border px-2.5 text-[12px] text-muted-foreground transition-colors hover:text-foreground"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {error ? <p className="shrink-0 text-[13px] text-danger">Could not refresh: {error}</p> : null}

      <div className="grid shrink-0 grid-cols-2 gap-3 xl:grid-cols-5">
        <Stat
          label="Personal accounts"
          value={String(data?.counts.personal ?? 0)}
          detail={`Public email domains, last ${data?.window_days ?? days} days`}
          tone={data?.counts.personal ? "text-danger" : "text-foreground"}
        />
        <Stat
          label="Corporate accounts"
          value={String(data?.counts.corporate ?? 0)}
          detail={`Other domains, last ${data?.window_days ?? days} days`}
        />
        <Stat
          label="Outside your list"
          value={approved.length ? String(outside) : "Not set"}
          detail={approved.length ? "Accounts not on your approved list" : "Add approved accounts below"}
          tone={approved.length && outside ? "text-danger" : "text-foreground"}
        />
        <Stat
          label="Sessions, account unknown"
          value={String(data?.sessions_without_account ?? 0)}
          detail={`Of ${data?.sessions ?? 0} sessions in this window`}
          tone={data?.sessions_without_account ? "text-caution" : "text-foreground"}
        />
        <Stat
          label="Agents, account unknown"
          value={String(unknownAgents)}
          detail={`Of ${agents.length} ${agents.length === 1 ? "agent" : "agents"} seen in this window`}
          tone={unknownAgents ? "text-caution" : "text-foreground"}
        />
      </div>

      <div className="flex shrink-0 items-start gap-2 rounded-sm border border-border bg-muted/30 px-3 py-2.5 text-[12px] leading-relaxed text-muted-foreground">
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <p>
          This is what agents reported, not verified identity. It shows nothing from before Agentmetry was installed, from an agent with no hook, or from a browser. Sessions recorded before account capture existed count as unknown. Full email addresses appear only if{" "}
          <code className="font-mono">AGENTMETRY_LOG_ACCOUNT_EMAIL=1</code> was set when the event was recorded.
        </p>
      </div>

      {data?.truncated ? (
        <p className="shrink-0 text-[13px] text-caution">This window holds more events than one page reads, so these totals are partial. Choose a shorter window.</p>
      ) : null}

      {accounts.length === 0 ? (
        <section className="panel shrink-0">
          <EmptyState icon={<UserSearch className="h-5 w-5" />}>
            No agent reported an account in this window. Cursor, Claude Code and Codex can report one. Run a session in any of them, then refresh.
          </EmptyState>
        </section>
      ) : (
        ACCOUNT_SECTIONS.map((section) => {
          const rows = accountsOfKind(accounts, section.kind);
          // Personal and corporate always show, so an empty one reads as a
          // finding. The third exists only when something needs it.
          if (rows.length === 0 && !section.empty) return null;
          return (
            <section key={section.kind} className="panel shrink-0" aria-label={section.title}>
              <header className="border-b border-border px-4 py-3">
                <p className="eyebrow">
                  {section.title} <span className="font-mono">({rows.length})</span>
                </p>
                <p className="mt-1 text-[12px] text-muted-foreground">{section.note}</p>
              </header>
              {rows.length ? (
                <AccountsTable accounts={rows} approved={approved} onOpenDetection={onOpenDetection} />
              ) : (
                <p className="px-4 py-3 text-[13px] text-muted-foreground">{section.empty}</p>
              )}
            </section>
          );
        })
      )}

      <div className="grid shrink-0 gap-3 lg:grid-cols-2">
        <section className="panel">
          <header className="border-b border-border px-4 py-3">
            <p className="eyebrow">Agent coverage</p>
          </header>
          {agents.length ? (
            <CoverageList agents={agents} />
          ) : (
            <EmptyState>No agent activity in this window.</EmptyState>
          )}
        </section>
        <section className="panel">
          <header className="border-b border-border px-4 py-3">
            <p className="eyebrow">Approved accounts</p>
          </header>
          <div className="space-y-2 px-4 py-3">
            <label htmlFor="identity-approved" className="block text-[12px] leading-relaxed text-muted-foreground">
              Domains or account IDs your company has approved, separated by commas or new lines. Subdomains count. Anything else is marked as outside your list, in either section. This list stays in this browser.
            </label>
            <textarea
              id="identity-approved"
              rows={3}
              value={listText}
              spellCheck={false}
              placeholder="company.example"
              onChange={(event) => {
                setListText(event.target.value);
                storeList(event.target.value);
              }}
              className="w-full rounded-sm border border-border bg-background px-2.5 py-2 font-mono text-[13px] outline-none focus:border-signal"
            />
          </div>
        </section>
      </div>
    </div>
  );
}
