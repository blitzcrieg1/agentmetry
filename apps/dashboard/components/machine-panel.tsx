"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw, X } from "lucide-react";
import { apiHeaders } from "@/lib/api";
import { sourceLabel } from "@/lib/audit-source";
import {
  agentsByAttention,
  dlpModeSentence,
  listingSentence,
  mcpFindingLabel,
  policyModeSentence,
  type MachineSnapshot,
  type McpServerRow,
  AGENT_STATE_LABEL,
} from "@/lib/machine";
import { ORCHESTRATOR_URL } from "@/lib/utils";
import { EmptyState, SeverityBadge } from "@/components/ui/kit";

function serverKey(row: McpServerRow): string {
  return `${row.agent}:${row.scope}:${row.name}`;
}

function StatePill({ state }: { state: MachineSnapshot["agents"][number]["state"] }) {
  const tone =
    state === "uncovered"
      ? "bg-danger/10 text-danger"
      : state === "covered"
        ? "bg-secure/15 text-secure"
        : state === "unknown"
          ? "bg-caution/15 text-caution"
          : "bg-muted text-subtle";
  return (
    <span className={`inline-flex items-center rounded-sm px-2 py-0.5 font-mono text-[11px] font-medium uppercase tracking-[0.04em] ${tone}`}>
      {AGENT_STATE_LABEL[state]}
    </span>
  );
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

function actionTone(action: string): string {
  if (action === "deny") return "bg-danger/10 text-danger";
  if (action === "ask") return "bg-caution/15 text-caution";
  return "bg-secure/15 text-secure";
}

export function MachinePanel() {
  const [data, setData] = useState<MachineSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAbsent, setShowAbsent] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${ORCHESTRATOR_URL}/api/v1/audit/machine`, {
        headers: apiHeaders(),
        credentials: "include",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData((await res.json()) as MachineSnapshot);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not read this machine");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!selected) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelected(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selected]);

  const agents = useMemo(() => agentsByAttention(data?.agents ?? []), [data]);
  const installed = agents.filter((agent) => agent.state !== "absent");
  const absent = agents.filter((agent) => agent.state === "absent");
  const uncovered = agents.filter((agent) => agent.state === "uncovered");
  const covered = agents.filter((agent) => agent.state === "covered");
  const flagged = (data?.mcp.servers ?? []).filter((server) => server.findings.length > 0);
  const open = data?.mcp.servers.find((server) => serverKey(server) === selected) ?? null;
  const high = data?.posture.counts.high ?? 0;

  if (loading && !data) {
    return <p className="px-1 py-6 text-[13px] text-muted-foreground">Reading this machine…</p>;
  }
  if (error && !data) {
    return (
      <EmptyState>
        <p>{error}</p>
        <button type="button" className="btn mt-3" onClick={() => void load()}>
          Try again
        </button>
      </EmptyState>
    );
  }
  if (!data) return null;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto">
      {data.profile === "service" ? (
        <p className="rounded-sm border border-caution/40 bg-caution/10 px-3 py-2 text-[13px] text-caution">
          This process is a service account. It cannot see a developer&apos;s agent configuration, so the rows below are unknown rather than clear.
        </p>
      ) : null}

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Stat
          label="Recorded"
          value={`${covered.length}`}
          detail={installed.length ? `of ${installed.length} installed here` : "no agent installed here"}
          tone={covered.length && uncovered.length === 0 ? "text-secure" : "text-foreground"}
        />
        <Stat
          label="Not recorded"
          value={`${uncovered.length}`}
          detail={uncovered.length ? uncovered.map((agent) => sourceLabel(agent.name)).join(", ") : "every installed agent is hooked"}
          tone={uncovered.length ? "text-danger" : "text-foreground"}
        />
        <Stat
          label="Posture"
          value={`${high}`}
          detail={high ? "high findings, a prompt or a hook is skipped" : "no high findings"}
          tone={high ? "text-signal" : "text-foreground"}
        />
        <Stat
          label="MCP servers"
          value={`${data.mcp.servers.length}`}
          detail={flagged.length ? `${flagged.length} with a configuration finding` : "none flagged from the config file"}
          tone={flagged.length ? "text-signal" : "text-foreground"}
        />
      </div>

      <div className="grid gap-3 xl:grid-cols-2">
        <section className="panel">
          <header className="flex items-center justify-between border-b border-border px-4 py-3">
            <h2 className="text-[14px] font-medium">Agents on this machine</h2>
            <button type="button" className="btn" onClick={() => void load()} aria-label="Refresh">
              <RefreshCw className="h-3.5 w-3.5" />
            </button>
          </header>
          <ul className="divide-y divide-border">
            {(showAbsent ? agents : installed).map((agent) => (
              <li key={agent.name} className="flex items-center justify-between gap-3 px-4 py-2.5">
                <span className="text-[14px]">{sourceLabel(agent.name)}</span>
                <StatePill state={agent.state} />
              </li>
            ))}
            {installed.length === 0 ? (
              <li className="px-4 py-6 text-[13px] text-muted-foreground">No supported agent is installed here.</li>
            ) : null}
          </ul>
          {absent.length ? (
            <button
              type="button"
              className="w-full border-t border-border px-4 py-2.5 text-left text-[12px] text-muted-foreground hover:text-foreground"
              onClick={() => setShowAbsent((open) => !open)}
            >
              {showAbsent ? "Hide" : "Show"} {absent.length} not installed
            </button>
          ) : null}
        </section>

        <section className="panel">
          <header className="border-b border-border px-4 py-3">
            <h2 className="text-[14px] font-medium">Settings that skip a prompt</h2>
          </header>
          {data.posture.findings.length === 0 ? (
            <EmptyState>No setting that removes a person or a hook was found in the files this check reads.</EmptyState>
          ) : (
            <ul className="divide-y divide-border">
              {data.posture.findings.map((finding) => (
                <li key={`${finding.agent}:${finding.scope}:${finding.setting}`} className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <SeverityBadge severity={finding.severity} />
                    <span className="text-[13px] font-medium">{sourceLabel(finding.agent)}</span>
                    <span className="font-mono text-[11px] text-subtle">{finding.scope}</span>
                  </div>
                  <p className="mt-1.5 font-mono text-[12px] text-foreground">
                    {finding.setting} = {finding.value}
                  </p>
                  <p className="mt-1 text-[12px] text-muted-foreground">{finding.why}</p>
                </li>
              ))}
            </ul>
          )}
          <footer className="space-y-1 border-t border-border px-4 py-3 text-[12px] text-muted-foreground">
            {data.posture.not_checked.map((item) => (
              <p key={item.agent}>
                {sourceLabel(item.agent)} is not checked: {item.why}.
              </p>
            ))}
            {data.posture.unreadable ? <p>{data.posture.unreadable} settings file(s) could not be read.</p> : null}
          </footer>
        </section>
      </div>

      <section className="panel">
        <header className="flex flex-wrap items-end justify-between gap-2 border-b border-border px-4 py-3">
          <div>
            <h2 className="text-[14px] font-medium">MCP servers</h2>
            <p className="mt-0.5 text-[12px] text-muted-foreground">
              Configured here. A listing is recorded only when the server runs behind the proxy.
            </p>
          </div>
          <p className="font-mono text-[11px] text-subtle">
            config {data.mcp.config_digest || "—"}
            {data.mcp.schema_digest ? ` · schema ${data.mcp.schema_digest}` : ""}
          </p>
        </header>
        {data.mcp.servers.length === 0 ? (
          <EmptyState>No MCP server is configured for the agents this check reads.</EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[13px]">
              <thead>
                <tr className="eyebrow border-b border-border">
                  <th className="px-4 py-2 font-medium">Server</th>
                  <th className="px-4 py-2 font-medium">Agent</th>
                  <th className="px-4 py-2 font-medium">Transport</th>
                  <th className="px-4 py-2 font-medium">Finding</th>
                </tr>
              </thead>
              <tbody>
                {data.mcp.servers.map((server) => (
                  <tr
                    key={serverKey(server)}
                    tabIndex={0}
                    className="cursor-pointer border-b border-border last:border-0 hover:bg-muted/60 focus-visible:bg-muted/60 focus-visible:outline-none"
                    onClick={() => setSelected(serverKey(server))}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        setSelected(serverKey(server));
                      }
                    }}
                  >
                    <td className="px-4 py-2.5 font-medium">{server.name}</td>
                    <td className="px-4 py-2.5 text-muted-foreground">{sourceLabel(server.agent)}</td>
                    <td className="px-4 py-2.5 font-mono text-[12px] text-muted-foreground">{server.transport}</td>
                    <td className="px-4 py-2.5 text-muted-foreground">
                      {server.findings.length
                        ? `${mcpFindingLabel(server.findings[0])}${server.findings.length > 1 ? ` +${server.findings.length - 1}` : ""}`
                        : "None from the config file"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel">
        <header className="border-b border-border px-4 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-[14px] font-medium">Tool policy</h2>
            <span className={`rounded-sm px-2 py-0.5 font-mono text-[11px] uppercase ${actionTone(data.policy.mode === "block" ? "deny" : "allow")}`}>
              {data.policy.mode}
            </span>
            <span className="text-[12px] text-muted-foreground">default {data.policy.default}</span>
          </div>
          <p className="mt-1 text-[12px] text-muted-foreground">{policyModeSentence(data.policy.mode)}</p>
        </header>
        <ul className="divide-y divide-border">
          {data.policy.rules.map((rule) => (
            <li key={rule.id} className="flex items-start gap-3 px-4 py-2.5">
              <span className={`mt-0.5 shrink-0 rounded-sm px-2 py-0.5 font-mono text-[11px] uppercase ${actionTone(rule.action)}`}>
                {rule.action}
              </span>
              <div className="min-w-0">
                <p className="text-[13px]">{rule.description || rule.id}</p>
                <p className="mt-0.5 font-mono text-[11px] text-subtle">
                  {rule.id}
                  {rule.matches_command ? " · matches the command" : ""}
                  {` · ${rule.tools} tool pattern${rule.tools === 1 ? "" : "s"}`}
                </p>
              </div>
            </li>
          ))}
        </ul>
        <footer className="space-y-1 border-t border-border px-4 py-3 text-[12px] text-muted-foreground">
          <p>
            Ask reaches a person for{" "}
            {data.policy.ask_reaches.map((pair) => `${sourceLabel(pair.agent)} ${pair.hook}`).join(", ")}.
            Elsewhere an ask is enforced as deny.
          </p>
          <p>{dlpModeSentence(data.policy.dlp_mode, data.policy.dlp_rules)}</p>
        </footer>
      </section>

      {open ? (
        <div className="fixed inset-0 z-40 flex justify-end bg-black/40" onClick={() => setSelected(null)}>
          <aside
            role="dialog"
            aria-modal="true"
            aria-labelledby="mcp-detail-title"
            className="flex h-full w-full max-w-md flex-col border-l border-border bg-card shadow-xl"
            onClick={(event) => event.stopPropagation()}
          >
            <header className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
              <div>
                <p className="eyebrow">{sourceLabel(open.agent)} · {open.scope}</p>
                <h2 id="mcp-detail-title" className="mt-1 text-[18px] font-semibold">{open.name}</h2>
              </div>
              <button type="button" className="btn" onClick={() => setSelected(null)} aria-label="Close">
                <X className="h-3.5 w-3.5" />
              </button>
            </header>
            <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4 text-[13px]">
              <dl className="grid grid-cols-[7rem_1fr] gap-y-2">
                <dt className="text-subtle">Transport</dt>
                <dd className="font-mono text-[12px]">{open.transport}</dd>
                <dt className="text-subtle">Launcher</dt>
                <dd className="font-mono text-[12px]">{open.launcher || "—"}</dd>
                <dt className="text-subtle">Package</dt>
                <dd className="font-mono text-[12px]">{open.package || "—"}</dd>
                <dt className="text-subtle">Host</dt>
                <dd className="font-mono text-[12px]">{open.url_host || "—"}</dd>
                <dt className="text-subtle">Config</dt>
                <dd className="font-mono text-[12px]">{open.fingerprint}</dd>
              </dl>
              <div>
                <p className="eyebrow mb-2">Configuration</p>
                {open.findings.length === 0 ? (
                  <p className="text-muted-foreground">Nothing in the config file is flagged.</p>
                ) : (
                  <ul className="space-y-1.5">
                    {open.findings.map((code) => (
                      <li key={code}>{mcpFindingLabel(code)}</li>
                    ))}
                  </ul>
                )}
              </div>
              <div>
                <p className="eyebrow mb-2">What the model was handed</p>
                <p className="text-muted-foreground">{listingSentence(open)}</p>
                {open.observed_at ? (
                  <p className="mt-1 font-mono text-[11px] text-subtle">Last listed {open.observed_at}</p>
                ) : null}
              </div>
              <p className="text-[12px] text-subtle">
                Arguments and environment values stay on this machine and are not shown here.
              </p>
            </div>
          </aside>
        </div>
      ) : null}
    </div>
  );
}
