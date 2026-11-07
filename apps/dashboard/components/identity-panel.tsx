"use client";

import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Check, ChevronDown, ChevronRight, Copy, Info, RefreshCw, UserSearch } from "lucide-react";
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
  approvedListStatus,
  countOutside,
  organizationSummary,
  parseApprovedDomains,
  shortTime,
  shownAgents,
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

function Stat({
  label,
  value,
  detail,
  tone = "text-foreground",
  action,
}: {
  label: string;
  value: string;
  detail: string;
  tone?: string;
  action?: ReactNode;
}) {
  return (
    <div className="panel px-4 py-3">
      <p className="eyebrow">{label}</p>
      <p className={`mt-1 font-mono text-[22px] font-medium leading-none ${tone}`}>{value}</p>
      <p className="mt-1.5 text-[12px] text-muted-foreground">{detail}</p>
      {action}
    </div>
  );
}

function CountPill({ label, value, of, attention }: { label: string; value: number; of?: number; attention: boolean }) {
  return (
    <span className="whitespace-nowrap text-[12px] text-muted-foreground">
      {label}{" "}
      <span className={`font-mono font-medium ${attention ? "text-caution" : "text-foreground"}`}>
        {value}
        {of === undefined ? "" : ` of ${of}`}
      </span>
    </span>
  );
}

function CopyValue({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* The value stays selectable on the page. */
    }
  };
  return (
    <span className="flex items-start gap-1.5">
      <span className="min-w-0 break-all font-mono text-[12px]">{value}</span>
      <button
        type="button"
        aria-label={copied ? `${label} copied` : `Copy ${label}`}
        title={copied ? "Copied" : `Copy ${label}`}
        onClick={() => void copy()}
        className="shrink-0 rounded-sm p-0.5 text-muted-foreground transition-colors hover:text-foreground"
      >
        {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
    </span>
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
          <h3 className="eyebrow mb-1">Reported source</h3>
          <ul className="space-y-0.5">
            {account.sources.length ? (
              account.sources.map((source) => <li key={source}>{accountSourceLabel(source)}</li>)
            ) : (
              <li className="text-muted-foreground">Not stated</li>
            )}
          </ul>
        </div>
        <div>
          <h3 className="eyebrow mb-1">Agents</h3>
          <p>{account.agents.map(sourceLabel).join(", ")}</p>
        </div>
        {account.emails.length ? (
          <div>
            <h3 className="eyebrow mb-1">Email addresses</h3>
            <ul className="space-y-0.5">
              {account.emails.map((email) => (
                <li key={email}>
                  <CopyValue value={email} label="email address" />
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {account.organization_ids.length ? (
          <div>
            <h3 className="eyebrow mb-1">{account.organization_ids.length === 1 ? "Organization ID" : "Organization IDs"}</h3>
            <ul className="space-y-0.5">
              {account.organization_ids.map((id) => (
                <li key={id}>
                  <CopyValue value={id} label="organization ID" />
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {account.account_id ? (
          <div>
            <h3 className="eyebrow mb-1">Account ID</h3>
            <CopyValue value={account.account_id} label="account ID" />
          </div>
        ) : null}
        {account.user_id ? (
          <div>
            <h3 className="eyebrow mb-1">User ID</h3>
            <CopyValue value={account.user_id} label="user ID" />
          </div>
        ) : null}
        <div>
          <h3 className="eyebrow mb-1">Operating system accounts</h3>
          <p className="break-words font-mono text-[12px]">{account.operators.join(", ") || "None recorded"}</p>
        </div>
        <div>
          <h3 className="eyebrow mb-1">Hosts</h3>
          <p className="break-words font-mono text-[12px]">{account.hosts.join(", ") || "None recorded"}</p>
        </div>
        <div>
          <h3 className="eyebrow mb-1">Seen</h3>
          <p className="text-[12px] text-muted-foreground" title={`${account.first_seen} to ${account.last_seen}`}>
            {shortTime(account.first_seen)} to {shortTime(account.last_seen)}
          </p>
        </div>
      </div>
      <div className="min-w-0">
        <h3 className="eyebrow mb-1">Detections on this domain or account</h3>
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
                  <span className="shrink-0 text-[12px] text-muted-foreground" title={detection.timestamp_utc}>
                    {shortTime(detection.timestamp_utc)}
                  </span>
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
      {/* Fixed widths, so the columns line up across the sections on the page. */}
      <table className="w-full min-w-[760px] table-fixed text-left text-[13px]">
        <colgroup>
          <col className="w-[25%]" />
          <col className="w-[13%]" />
          <col className="w-[21%]" />
          <col className="w-[9%]" />
          <col className="w-[17%]" />
          <col className="w-[15%]" />
        </colgroup>
        <thead>
          <tr className="border-b border-border text-[12px] text-muted-foreground">
            <th className="px-4 py-2 font-medium">Domain or account ID</th>
            <th className="px-3 py-2 font-medium">Approval</th>
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
            const { shown, hidden } = shownAgents(account.agents);
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
                      {shown.map((agent) => (
                        <span key={agent} className="inline-flex items-center gap-1.5 whitespace-nowrap">
                          <AgentTile app={agent} size="sm" />
                          {sourceLabel(agent)}
                        </span>
                      ))}
                      {hidden.length ? (
                        <span className="text-[12px] text-muted-foreground" title={hidden.map(sourceLabel).join(", ")}>
                          +{hidden.length} more
                        </span>
                      ) : null}
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
                  <td className="px-3 py-2.5 text-[12px] text-muted-foreground" title={account.last_seen}>
                    {shortTime(account.last_seen)}
                  </td>
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
  const listBox = useRef<HTMLTextAreaElement>(null);

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

      <div className="grid shrink-0 gap-3 sm:grid-cols-3">
        <Stat
          label="Personal domains"
          value={String(data?.counts.personal ?? 0)}
          detail={`Public email domains, last ${data?.window_days ?? days} days`}
          tone={data?.counts.personal ? "text-danger" : "text-foreground"}
        />
        <Stat
          label="Outside your list"
          value={approved.length ? String(outside) : "Not set"}
          detail={approved.length ? "Not on your approved list" : "No approved list yet"}
          tone={approved.length && outside ? "text-danger" : "text-foreground"}
          action={
            <button
              type="button"
              onClick={() => {
                listBox.current?.scrollIntoView({ behavior: "smooth", block: "center" });
                listBox.current?.focus({ preventScroll: true });
              }}
              className="mt-1.5 text-[12px] font-medium text-signal hover:underline"
            >
              Edit approved list
            </button>
          }
        />
        <Stat
          label="Other domains"
          value={String(data?.counts.corporate ?? 0)}
          detail={`Not a known public provider, last ${data?.window_days ?? days} days`}
        />
      </div>

      <div className="panel flex shrink-0 flex-wrap items-center gap-x-5 gap-y-1 px-4 py-2.5" role="group" aria-label="Where the account is unknown">
        <CountPill label="Sessions, account unknown" value={data?.sessions_without_account ?? 0} of={data?.sessions ?? 0} attention={Boolean(data?.sessions_without_account)} />
        <CountPill label="Agents, account unknown" value={unknownAgents} of={agents.length} attention={unknownAgents > 0} />
        <CountPill label="Accounts with no domain" value={data?.counts.unclassified ?? 0} attention={false} />
      </div>

      <div className="flex shrink-0 items-start gap-2 rounded-sm border border-border bg-muted/30 px-3 py-2.5 text-[12px] leading-relaxed text-muted-foreground">
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <div className="min-w-0">
          <p>
            Reported by the agents, not verified identity. A last sign-in source means the account last signed in on this machine, not necessarily the one that made the call.
          </p>
          <details className="mt-1">
            <summary className="cursor-pointer font-medium text-foreground">What this page cannot show</summary>
            <p className="mt-1">
              Nothing from before Agentmetry was installed, from an agent with no hook, or from a browser. Sessions recorded before account capture existed count as unknown. Full email addresses appear only if{" "}
              <code className="font-mono">AGENTMETRY_LOG_ACCOUNT_EMAIL=1</code> was set when the event was recorded.
            </p>
          </details>
        </div>
      </div>

      {data?.truncated ? (
        <p className="shrink-0 text-[13px] text-caution">This window holds more events than one page reads, so these totals are partial. Choose a shorter window.</p>
      ) : null}

      {accounts.length === 0 ? (
        <section className="panel shrink-0">
          <EmptyState icon={<UserSearch className="h-5 w-5" />}>
            No agent reported an account in this window. Cursor, Claude Code, Codex and Antigravity can report one. Run a session in any of them, then refresh.
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
                <h2 className="eyebrow">
                  {section.title} <span className="font-mono">({rows.length})</span>
                </h2>
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

      <div className="grid shrink-0 items-start gap-3 lg:grid-cols-2">
        <section className="panel">
          <header className="border-b border-border px-4 py-3">
            <h2 className="eyebrow">Agent coverage</h2>
          </header>
          {agents.length ? (
            <CoverageList agents={agents} />
          ) : (
            <EmptyState>No agent activity in this window.</EmptyState>
          )}
        </section>
        <section className="panel">
          <header className="border-b border-border px-4 py-3">
            <h2 className="eyebrow">Approved accounts</h2>
          </header>
          <div className="space-y-2 px-4 py-3">
            <label htmlFor="identity-approved" className="block text-[12px] leading-relaxed text-muted-foreground">
              Domains or account IDs your company has approved, separated by commas or new lines. Subdomains count. Anything else is marked as outside your list, in either section. This list stays in this browser.
            </label>
            <textarea
              id="identity-approved"
              ref={listBox}
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
            <p className="text-[12px] text-muted-foreground" aria-live="polite">
              {approvedListStatus(approved)}
            </p>
          </div>
        </section>
      </div>
    </div>
  );
}
