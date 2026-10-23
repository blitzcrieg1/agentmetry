"use client";

import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, CircleAlert, Hand, Search, ShieldAlert, Zap } from "lucide-react";
import { AgentMark } from "@/components/ui/agent-mark";
import { FAMILY_ICON } from "@/components/investigation/family-icon";
import { type FamilyCount, SIGNAL_LABEL, kindLabel, signalOf } from "@/lib/investigation";
import { type SessionNode, shortTool } from "@/lib/session-tree";

function clock(ts: string): string {
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? ts : d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

const COUNTERS: { key: keyof Pick<FamilyCount, "calls" | "cited" | "flagged" | "refused" | "errors" | "asked">; label: string; icon: typeof Zap; tone: string }[] = [
  { key: "calls", label: "Events", icon: Zap, tone: "text-foreground" },
  { key: "cited", label: "Cited", icon: ShieldAlert, tone: "text-danger" },
  { key: "flagged", label: "Flagged", icon: CircleAlert, tone: "text-caution" },
  { key: "errors", label: "Errors", icon: CircleAlert, tone: "text-danger" },
  { key: "asked", label: "Asked", icon: Hand, tone: "text-foreground" },
];

/**
 * The session as rows: the agent at the top, one row per tool category with
 * its counters, and each category opening into its calls. Counts cover the
 * events loaded for this investigation.
 */
export function ActivityTable({
  app,
  appLabel,
  families,
  cited,
  selectedId,
  onSelect,
  truncated,
  total,
}: {
  app: string;
  appLabel: string;
  families: FamilyCount[];
  cited: Set<string>;
  selectedId: string | null;
  onSelect: (id: string) => void;
  truncated: boolean;
  total?: number;
}) {
  const [open, setOpen] = useState<Set<string>>(() => new Set(families.filter((f) => f.cited).map((f) => f.key)));
  const [query, setQuery] = useState("");
  const needle = query.trim().toLowerCase();
  const match = (n: SessionNode) =>
    !needle ||
    [shortTool(n), n.tool.qualified, n.tool.command, n.reason, n.kind, n.outcome].filter(Boolean).join(" ").toLowerCase().includes(needle);
  const totals = useMemo(() => {
    const t = { calls: 0, cited: 0, flagged: 0, refused: 0, errors: 0, asked: 0 };
    for (const f of families) for (const k of Object.keys(t) as (keyof typeof t)[]) t[k] += f[k];
    return t;
  }, [families]);
  const toggle = (key: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  return (
    <section className="flex min-h-0 flex-1 flex-col" aria-label="Activity table">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-2.5">
        <p className="text-[12px] text-muted-foreground">One row per tool category. Flagged means refused, or a policy or DLP match. Open a row to see its calls.</p>
        <label className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-subtle" aria-hidden />
          <input value={query} onChange={(e) => setQuery(e.target.value)} className="control h-8 w-56 pl-8 text-[12px]" placeholder="Filter calls" aria-label="Filter calls" />
        </label>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full min-w-[640px] border-collapse text-left text-[12px]">
          <thead className="sticky top-0 z-10 bg-card">
            <tr className="border-b border-border">
              <th className="px-3 py-2 font-medium text-subtle">Activity</th>
              {COUNTERS.map(({ key, label, icon: Icon }) => (
                <th key={key} className="px-2 py-2 text-right font-medium text-subtle" title={label}>
                  <span className="inline-flex items-center gap-1"><Icon className="h-3.5 w-3.5" aria-hidden />{label}</span>
                </th>
              ))}
              <th className="w-8" />
            </tr>
          </thead>
          <tbody>
            <tr className="border-b border-border bg-muted/30">
              <td className="px-3 py-2.5">
                <span className="inline-flex items-center gap-2 font-semibold">
                  <AgentMark app={app} size="sm" /> {appLabel || "Agent"} <span className="font-normal text-subtle">session</span>
                </span>
              </td>
              {COUNTERS.map(({ key, tone }) => (
                <td key={key} className={`px-2 py-2.5 text-right font-mono ${totals[key] ? tone : "text-subtle"}`}>{totals[key].toLocaleString()}</td>
              ))}
              <td />
            </tr>
            {families.map((f, i) => {
              const Icon = FAMILY_ICON[f.family];
              const rows = f.nodes.filter(match);
              const isOpen = open.has(f.key) || (needle !== "" && rows.length > 0);
              const Chevron = isOpen ? ChevronDown : ChevronRight;
              const last = i === families.length - 1;
              return [
                <tr key={f.key} className="border-b border-border/70 hover:bg-muted/40">
                  <td className="py-2 pl-3 pr-3">
                    <button type="button" aria-expanded={isOpen} onClick={() => toggle(f.key)} className="flex items-center gap-2 text-left">
                      <span className="relative h-6 w-5 shrink-0" aria-hidden>
                        <span className={`absolute left-2 top-0 border-l border-border ${last ? "h-3" : "h-6"}`} />
                        <span className="absolute left-2 top-3 w-3 border-t border-border" />
                      </span>
                      <Chevron className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
                      <Icon className="h-4 w-4 text-muted-foreground" aria-hidden />
                      <span className="font-medium underline-offset-2 hover:underline">{f.label}</span>
                    </button>
                  </td>
                  {COUNTERS.map(({ key, tone }) => (
                    <td key={key} className={`px-2 py-2 text-right font-mono ${f[key] ? tone : "text-subtle"}`}>{f[key].toLocaleString()}</td>
                  ))}
                  <td className="pr-3 text-right">
                    <button type="button" onClick={() => toggle(f.key)} className="rounded-md border border-border p-0.5 text-muted-foreground hover:bg-muted" aria-label={isOpen ? `Close ${f.label}` : `Open ${f.label}`}>
                      <Chevron className="h-3.5 w-3.5" />
                    </button>
                  </td>
                </tr>,
                isOpen ? (
                  <tr key={`${f.key}:calls`} className="border-b border-border/70 bg-background/60">
                    <td colSpan={COUNTERS.length + 2} className="p-0">
                      {rows.length ? (
                        <ul className="max-h-80 divide-y divide-border/60 overflow-auto">
                          {rows.slice(0, 500).map((n) => {
                            const s = signalOf(n, cited);
                            return (
                              <li key={n.id}>
                                <button
                                  type="button"
                                  aria-pressed={n.id === selectedId}
                                  onClick={() => onSelect(n.id)}
                                  className={`grid w-full grid-cols-[6rem_11rem_minmax(0,1fr)_9rem] items-center gap-3 py-2 pl-14 pr-4 text-left transition-colors hover:bg-muted/60 ${
                                    n.id === selectedId ? "bg-signal/[0.08]" : s === "cited" ? "bg-danger/[0.04]" : ""
                                  }`}
                                >
                                  <span className="font-mono text-muted-foreground">{clock(n.timestamp_utc)}</span>
                                  <span className="truncate font-mono font-medium">{shortTool(n)}</span>
                                  <span className="truncate font-mono text-muted-foreground" title={n.tool.command || n.reason}>{n.tool.command || n.reason || kindLabel(n)}</span>
                                  <span className={`truncate text-right ${s === "cited" ? "text-danger" : s ? "text-caution" : "text-subtle"}`}>{s ? SIGNAL_LABEL[s] : n.outcome || "recorded"}</span>
                                </button>
                              </li>
                            );
                          })}
                          {rows.length > 500 ? <li className="py-2 pl-14 text-subtle">First 500 of {rows.length.toLocaleString()} shown. Filter to narrow.</li> : null}
                        </ul>
                      ) : (
                        <p className="py-3 pl-14 text-subtle">No calls in this category match the filter.</p>
                      )}
                    </td>
                  </tr>
                ) : null,
              ];
            })}
          </tbody>
        </table>
      </div>
      <div className="border-t border-border px-4 py-2 text-[12px] text-subtle">
        {truncated ? (
          <span className="text-caution">A window of a longer session{total ? ` (${total.toLocaleString()} events in all)` : ""}. The event stream has the rest.</span>
        ) : (
          "Every event loaded for this session is counted above."
        )}
      </div>
    </section>
  );
}
