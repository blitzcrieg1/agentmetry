"use client";

import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  Ban,
  Bot,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  FileText,
  Globe,
  ListTree,
  Monitor,
  Plug,
  ShieldAlert,
  TerminalSquare,
  Users,
  Wrench,
} from "lucide-react";
import type { Detection } from "@/components/flight-recorder-panel";
import { SeverityBadge, Technique, TechniqueChain } from "@/components/ui/kit";
import { AgentMark, AgentTile } from "@/components/ui/agent-mark";
import { StatusChip, TriagePanel, formatTime } from "@/components/triage-panel";
import { type Disposition, statusOf } from "@/lib/disposition";
import { sourceLabel } from "@/lib/audit-source";
import {
  type Branch,
  type Family,
  type Row,
  type SessionNode,
  type SessionTreePayload,
  approvalSentence,
  buildBranches,
  citedSet,
  fetchSessionTree,
  foldBranch,
  isCited,
  isFlagged,
  shortTool,
  timelinePct,
  toolFamily,
} from "@/lib/session-tree";

const FAMILY_ICON: Record<Family, typeof TerminalSquare> = {
  shell: TerminalSquare,
  files: FileText,
  web: Globe,
  mcp: Plug,
  subagents: Users,
  other: Wrench,
};

function shortId(id: string): string {
  return id.length > 20 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id;
}

function clock(ts?: string): string {
  if (!ts) return "";
  try {
    return new Date(ts).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return ts;
  }
}

function duration(first?: string | null, last?: string | null): string {
  const a = first ? Date.parse(first) : NaN;
  const b = last ? Date.parse(last) : NaN;
  if (!Number.isFinite(a) || !Number.isFinite(b) || b < a) return "";
  const minutes = Math.round((b - a) / 60000);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} h ${minutes % 60} min`;
  return `${Math.floor(hours / 24)} d ${hours % 24} h`;
}

function kindLabel(node: SessionNode): string {
  switch (node.kind) {
    case "denied":
      return "Asked, refused";
    case "ask":
      return node.approval === "expired" ? "Asked, the session ended first" : "Asked, no call recorded";
    case "subagent_start":
      return "Subagent started";
    case "subagent_stop":
      return "Subagent finished";
    default:
      return node.approval ? "Asked, then ran" : "Tool call";
  }
}

function policySentence(node: SessionNode): string | null {
  const p = node.tool_policy;
  if (!p?.rule_id) return null;
  if (p.mode === "block" && p.blocked) return `Stopped by ${p.rule_id} before it ran.`;
  if (p.blocked) return `Matched ${p.rule_id}. Policy is in ${p.mode ?? "log"} mode, so the call still ran.`;
  return `Matched ${p.rule_id} (${p.action ?? "rule"}, ${p.mode ?? "log"} mode).`;
}

function dlpSentence(node: SessionNode): string | null {
  const d = node.dlp;
  if (!d?.rule_id) return null;
  const tail = d.mode === "block" ? "It was stopped before it ran." : "DLP is in log mode, so the call still ran.";
  return `DLP rule ${d.rule_id}${d.category ? ` (${d.category})` : ""} matched. ${tail}`;
}

/**
 * A detection opened the way an EDR opens one: the lineage across the top, the
 * session's calls as a tree with the cited ones lit, and the selected call's
 * details beside the triage form. It replaces a side panel that loaded the
 * first 2,000 events of the session and so lost the cited calls of any long one.
 */
export function DetectionInvestigation({
  det,
  disposition,
  onDispositionSaved,
  onClose,
  onOpenInStream,
}: {
  det: Detection;
  disposition?: Disposition;
  onDispositionSaved: (updated: Disposition) => void;
  onClose: () => void;
  onOpenInStream: () => void;
}) {
  const [tree, setTree] = useState<SessionTreePayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // The parent keys this component by detection, so a different detection
  // mounts a fresh one and nothing here has to be reset by hand.
  useEffect(() => {
    let cancelled = false;
    fetchSessionTree(det.correlation_id, det.first_seen_utc)
      .then((payload) => {
        if (!cancelled) setTree(payload);
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [det.correlation_id, det.first_seen_utc]);

  const cited = useMemo(() => citedSet(det.event_ids ?? []), [det.event_ids]);
  const branches = useMemo(() => (tree ? buildBranches(tree.nodes, cited) : []), [tree, cited]);
  const citedNodes = useMemo(
    () => (tree ? tree.nodes.filter((n) => isCited(n, cited) && n.kind !== "detection") : []),
    [tree, cited],
  );
  const detectionsHere = useMemo(
    () => (tree ? tree.nodes.filter((n) => n.kind === "detection").length : 0),
    [tree],
  );
  const flaggedNodes = useMemo(() => (tree ? tree.nodes.filter(isFlagged) : []), [tree]);

  // Open on the first cited call, the way an EDR opens on the process that fired.
  const selected = useMemo(() => {
    if (!tree) return null;
    const id = selectedId ?? citedNodes[0]?.id ?? null;
    return tree.nodes.find((n) => n.id === id) ?? null;
  }, [tree, selectedId, citedNodes]);

  // The agent is the one that made the cited call. A session also carries
  // Agentmetry's own events, and `summary.apps` is alphabetical, so taking its
  // first entry named the recorder as the agent.
  const app = useMemo(() => {
    if (citedNodes[0]?.app) return citedNodes[0].app;
    const counts = new Map<string, number>();
    for (const n of tree?.nodes ?? []) if (n.app) counts.set(n.app, (counts.get(n.app) ?? 0) + 1);
    return [...counts].sort((a, b) => b[1] - a[1])[0]?.[0] ?? "";
  }, [citedNodes, tree]);
  const host = tree?.summary.hosts?.[0] ?? "";
  const missing = (det.event_ids ?? []).filter((id) => !tree?.nodes.some((n) => n.event_ids.includes(id)));
  const chain = det.technique_ids?.length ? det.technique_ids : det.tactic_ids;

  const toggleBranch = (key: string, open: boolean) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (open) next.delete(key);
      else next.add(key);
      return next;
    });
  const expand = (id: string) => setExpanded((prev) => new Set(prev).add(id));
  const showEverything = () => {
    setCollapsed(new Set());
    setExpanded(new Set(branches.map((b) => `${b.key}:*`)));
  };
  const showFocus = () => {
    setExpanded(new Set());
    setCollapsed(new Set());
  };
  const everything = branches.length > 0 && branches.every((b) => expanded.has(`${b.key}:*`));

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <header className="panel flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
        <button type="button" onClick={onClose} className="btn">
          <ArrowLeft className="h-3.5 w-3.5" />
          All detections
        </button>
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1">
          <SeverityBadge severity={det.severity} />
          <h2 className="min-w-0 text-[16px] font-semibold leading-snug">{det.title || det.rule_id}</h2>
          <span className="font-mono text-[12px] text-muted-foreground">{det.rule_id}</span>
          <StatusChip status={statusOf(disposition)} />
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-muted-foreground">
          {app ? (
            <span className="inline-flex items-center gap-1.5 text-foreground">
              <AgentMark app={app} size="sm" />
              {sourceLabel(app)}
            </span>
          ) : null}
          <span className="font-mono">{formatTime(det.first_seen_utc)}</span>
          {chain?.length ? <TechniqueChain ids={chain} /> : null}
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-3 xl:flex-row">
        <section className="panel flex min-h-[28rem] min-w-0 flex-1 flex-col overflow-hidden" aria-label="Process tree">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
            <div className="flex min-w-0 items-center gap-2">
              <ListTree className="h-4 w-4 text-muted-foreground" aria-hidden />
              <p className="text-[13px] font-medium">Process tree</p>
              {tree ? (
                <span className="truncate text-[12px] text-muted-foreground">
                  {(tree.summary.total ?? 0).toLocaleString()} events in this session,{" "}
                  {(tree.summary.by_type?.tool_called ?? 0).toLocaleString()} tool calls
                  {duration(tree.summary.first_utc, tree.summary.last_utc)
                    ? `, ${duration(tree.summary.first_utc, tree.summary.last_utc)}`
                    : ""}
                </span>
              ) : null}
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="btn"
                aria-pressed={everything}
                onClick={everything ? showFocus : showEverything}
                disabled={!tree}
              >
                {everything ? "Focus on the detection" : "Show every call"}
              </button>
            </div>
          </div>

          {tree ? <Timeline tree={tree} citedNodes={citedNodes} flagged={flaggedNodes} /> : null}

          <div className="min-h-0 flex-1 overflow-auto px-4 py-4">
            {loading ? (
              <p className="py-10 text-center text-[13px] text-muted-foreground">Loading the session…</p>
            ) : error ? (
              <p className="py-10 text-center text-[13px] text-danger">{error}</p>
            ) : !tree || tree.nodes.length === 0 ? (
              <p className="py-10 text-center text-[13px] text-muted-foreground">
                This session is no longer in the trail index.
              </p>
            ) : (
              <>
                <Lineage
                  host={host}
                  app={app}
                  adapter={citedNodes[0]?.adapter ?? tree.nodes[0]?.adapter ?? ""}
                  sessionId={det.correlation_id}
                  first={tree.summary.first_utc}
                  last={tree.summary.last_utc}
                  detectionsHere={detectionsHere}
                />
                <ul className="ml-[1.35rem] border-l border-border">
                  {branches.map((branch) => (
                    <BranchItem
                      key={branch.key}
                      branch={branch}
                      rows={foldBranch(branch, cited, expanded)}
                      open={!collapsed.has(branch.key) && (branch.cited > 0 || branch.flagged > 0 || expanded.has(`${branch.key}:*`) || branches.length <= 3)}
                      onToggle={(open) => {
                        toggleBranch(branch.key, open);
                        if (open && branch.cited === 0 && branch.flagged === 0) expand(`${branch.key}:*`);
                      }}
                      onExpand={expand}
                      selectedId={selected?.id ?? null}
                      autoFocus={selectedId === null}
                      onSelect={setSelectedId}
                    />
                  ))}
                </ul>
                {tree.truncated ? (
                  <p className="mt-4 text-[12px] text-muted-foreground">
                    This session is longer than one view holds. The tree shows the window either side of
                    the detection; the event stream has the rest.
                  </p>
                ) : null}
                {missing.length ? (
                  <p className="mt-2 text-[12px] text-caution">
                    {missing.length} of the events this detection cites are not in the trail index.
                  </p>
                ) : null}
                <p className="mt-4 text-[11px] leading-relaxed text-subtle">
                  Recorded at the tool boundary: each node is a call the agent made through its hooks. A shell
                  call is a process launch; what that process did inside is not in the trail. Subagents are
                  shown when they start and stop, and their calls stay on the parent session.
                </p>
              </>
            )}
          </div>
        </section>

        <aside className="panel flex min-h-0 w-full shrink-0 flex-col overflow-y-auto xl:w-[26rem]" aria-label="Details">
          <div className="space-y-5 p-4">
            {selected ? <NodeDetail node={selected} cited={isCited(selected, cited)} /> : null}
            <div className="space-y-2">
              <p className="eyebrow">Why it fired</p>
              <p className="text-[13px] leading-relaxed text-muted-foreground">{det.summary}</p>
              {chain?.length ? <TechniqueChain ids={chain} /> : null}
            </div>
            <TriagePanel det={det} disposition={disposition} onSaved={onDispositionSaved} />
            <button type="button" onClick={onOpenInStream} className="btn w-full" title="Open the whole session in the event stream">
              <ExternalLink className="h-3.5 w-3.5" />
              View session in event stream
            </button>
          </div>
        </aside>
      </div>
    </div>
  );
}

function Timeline({
  tree,
  citedNodes,
  flagged,
}: {
  tree: SessionTreePayload;
  citedNodes: SessionNode[];
  flagged: SessionNode[];
}) {
  const { first_utc: first, last_utc: last } = tree.summary;
  if (!first || !last) return null;
  return (
    <div className="border-b border-border px-4 py-3">
      <div className="relative h-5" aria-hidden>
        <div className="absolute inset-x-0 top-1/2 h-px bg-border" />
        {flagged.map((n) => (
          <span
            key={`f-${n.id}`}
            className="absolute top-1/2 h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-caution"
            style={{ left: `${timelinePct(n.timestamp_utc, first, last)}%` }}
          />
        ))}
        {citedNodes.map((n) => (
          <span
            key={`c-${n.id}`}
            className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-danger ring-2 ring-card"
            style={{ left: `${timelinePct(n.timestamp_utc, first, last)}%` }}
          />
        ))}
      </div>
      <div className="mt-1 flex items-center justify-between gap-3 font-mono text-[11px] text-subtle">
        <span>{formatTime(first)}</span>
        <span className="hidden items-center gap-3 sm:flex">
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full bg-danger" /> cited
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-caution" /> refused, or a DLP or policy match
          </span>
        </span>
        <span>{formatTime(last)}</span>
      </div>
    </div>
  );
}

function LineageCard({
  icon: Icon,
  mark,
  eyebrow,
  title,
  sub,
}: {
  icon?: typeof Monitor;
  mark?: ReactNode;
  eyebrow: string;
  title: string;
  sub?: string;
}) {
  return (
    <div className="panel flex min-w-0 items-center gap-3 px-3.5 py-2.5">
      {mark ?? (Icon ? (
        <span className="raised inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md">
          <Icon className="h-4 w-4 text-muted-foreground" aria-hidden />
        </span>
      ) : null)}
      <div className="min-w-0">
        <p className="eyebrow">{eyebrow}</p>
        <p className="truncate text-[14px] font-semibold" title={title}>
          {title}
        </p>
        {sub ? <p className="truncate font-mono text-[11px] text-subtle">{sub}</p> : null}
      </div>
    </div>
  );
}

function Lineage({
  host,
  app,
  adapter,
  sessionId,
  first,
  last,
  detectionsHere,
}: {
  host: string;
  app: string;
  adapter: string;
  sessionId: string;
  first?: string | null;
  last?: string | null;
  detectionsHere: number;
}) {
  const span = duration(first, last);
  return (
    <div className="mb-1 flex flex-wrap items-stretch gap-2">
      <LineageCard icon={Monitor} eyebrow="Machine" title={host || "This machine"} />
      <ChevronRight className="h-4 w-4 self-center text-subtle" aria-hidden />
      <LineageCard mark={app ? <AgentTile app={app} size="md" /> : undefined} icon={Bot} eyebrow="Agent" title={app ? sourceLabel(app) : "Agent"} sub={adapter || undefined} />
      <ChevronRight className="h-4 w-4 self-center text-subtle" aria-hidden />
      <LineageCard
        icon={TerminalSquare}
        eyebrow="Session"
        title={shortId(sessionId)}
        sub={[first ? `started ${clock(first)}` : "", span, detectionsHere > 1 ? `${detectionsHere} detections` : ""]
          .filter(Boolean)
          .join(", ")}
      />
    </div>
  );
}

function BranchItem({
  branch,
  rows,
  open,
  onToggle,
  onExpand,
  selectedId,
  autoFocus,
  onSelect,
}: {
  branch: Branch;
  rows: Row[];
  open: boolean;
  onToggle: (open: boolean) => void;
  onExpand: (id: string) => void;
  selectedId: string | null;
  autoFocus: boolean;
  onSelect: (id: string) => void;
}) {
  const Icon = FAMILY_ICON[branch.family];
  const Chevron = open ? ChevronDown : ChevronRight;
  return (
    <li className="relative pl-6 pt-3 before:absolute before:left-0 before:top-[1.6rem] before:w-5 before:border-t before:border-border">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => onToggle(!open)}
        className={`flex w-full items-center gap-2 rounded-sm border px-3 py-2 text-left transition-colors ${
          branch.cited ? "border-danger/40 bg-danger/[0.05]" : "border-border bg-background hover:border-foreground/25"
        }`}
      >
        <Chevron className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
        <Icon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
        <span className="text-[14px] font-semibold">{branch.label}</span>
        <span className="font-mono text-[11px] text-muted-foreground">
          {branch.nodes.length.toLocaleString()} {branch.nodes.length === 1 ? "call" : "calls"}
        </span>
        {branch.cited ? (
          <span className="inline-flex items-center gap-1 rounded-sm bg-danger/10 px-1.5 py-px font-mono text-[11px] text-danger">
            <ShieldAlert className="h-3 w-3" aria-hidden /> {branch.cited} cited
          </span>
        ) : null}
        {branch.flagged ? (
          <span className="rounded-sm bg-caution/10 px-1.5 py-px font-mono text-[11px] text-caution">{branch.flagged} flagged</span>
        ) : null}
      </button>
      {open ? (
        <ul className="ml-[1.1rem] border-l border-border">
          {rows.map((row) =>
            row.type === "fold" ? (
              <li key={row.id} className="relative pl-6 pt-1.5 before:absolute before:left-0 before:top-[1.15rem] before:w-5 before:border-t before:border-dashed before:border-border">
                <button
                  type="button"
                  onClick={() => onExpand(row.id)}
                  className="w-full rounded-sm border border-dashed border-border px-3 py-1.5 text-left font-mono text-[11px] text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground"
                >
                  {row.count.toLocaleString()} more {row.count === 1 ? "call" : "calls"}, {clock(row.fromUtc)} to {clock(row.toUtc)}. Show them
                </button>
              </li>
            ) : (
              <NodeItem
                key={row.node.id}
                node={row.node}
                cited={row.cited}
                selected={row.node.id === selectedId}
                focus={autoFocus && row.node.id === selectedId}
                onSelect={onSelect}
              />
            ),
          )}
        </ul>
      ) : null}
    </li>
  );
}

function NodeItem({
  node,
  cited,
  selected,
  focus,
  onSelect,
}: {
  node: SessionNode;
  cited: boolean;
  selected: boolean;
  focus: boolean;
  onSelect: (id: string) => void;
}) {
  const ref = useRef<HTMLButtonElement>(null);
  // On open, bring the cited call into view: in a long session it sits
  // hundreds of rows down, under the branches that come before it.
  useEffect(() => {
    if (focus) ref.current?.scrollIntoView({ block: "center" });
  }, [focus]);
  const denied = node.kind === "denied";
  const error = node.outcome === "error";
  const tone = cited
    ? "rise border-danger/60 bg-danger/[0.09]"
    : denied || node.tool_policy?.rule_id || node.dlp?.rule_id
      ? "border-caution/40 bg-caution/[0.05]"
      : "border-border bg-card hover:border-foreground/25";
  return (
    <li className="relative pl-6 pt-1.5 before:absolute before:left-0 before:top-[1.4rem] before:w-5 before:border-t before:border-border">
      <button
        ref={ref}
        type="button"
        aria-pressed={selected}
        onClick={() => onSelect(node.id)}
        className={`flex w-full min-w-0 items-start gap-2.5 rounded-sm border px-3 py-2 text-left transition-colors ${tone} ${
          selected ? "ring-2 ring-signal/60" : ""
        }`}
      >
        {denied ? (
          <Ban className="mt-0.5 h-3.5 w-3.5 shrink-0 text-caution" aria-hidden />
        ) : cited ? (
          <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-danger" aria-hidden />
        ) : (
          <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${error ? "bg-danger" : "bg-subtle"}`} aria-hidden />
        )}
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-1.5">
            <span className="font-mono text-[13px] font-semibold text-foreground">{shortTool(node)}</span>
            {cited ? <span className="rounded-sm bg-danger/15 px-1 py-px font-mono text-[10px] uppercase tracking-wide text-danger">cited</span> : null}
            {denied ? <span className="rounded-sm bg-caution/15 px-1 py-px font-mono text-[10px] uppercase tracking-wide text-caution">denied</span> : null}
            {error ? <span className="rounded-sm bg-danger/10 px-1 py-px font-mono text-[10px] uppercase tracking-wide text-danger">error</span> : null}
            {node.tool_policy?.rule_id ? <span className="rounded-sm bg-caution/10 px-1 py-px font-mono text-[10px] text-caution">policy</span> : null}
            {node.dlp?.rule_id ? <span className="rounded-sm bg-caution/10 px-1 py-px font-mono text-[10px] text-caution">dlp</span> : null}
            {node.tool.mitre?.technique_id ? <Technique id={node.tool.mitre.technique_id} tone={cited ? "alert" : "default"} /> : null}
          </span>
          {node.tool.command ? (
            <span className="mt-0.5 block truncate font-mono text-[12.5px] text-muted-foreground" title={node.tool.command}>
              {node.tool.command}
            </span>
          ) : node.kind.startsWith("subagent") ? (
            <span className="mt-0.5 block truncate text-[11.5px] text-muted-foreground">{node.reason.split(":").slice(1).join(":")}</span>
          ) : null}
        </span>
        <span className="shrink-0 font-mono text-[11px] text-subtle">{clock(node.timestamp_utc)}</span>
      </button>
    </li>
  );
}

function NodeDetail({ node, cited }: { node: SessionNode; cited: boolean }) {
  const family = toolFamily(node);
  const approval = approvalSentence(node);
  const policy = policySentence(node);
  const dlp = dlpSentence(node);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="eyebrow">Selected</p>
        {cited ? (
          <span className="inline-flex items-center gap-1 rounded-sm bg-danger/10 px-1.5 py-px font-mono text-[11px] text-danger">
            <ShieldAlert className="h-3 w-3" aria-hidden /> cited by this detection
          </span>
        ) : null}
      </div>
      <div>
        <p className="font-mono text-[14px] font-medium">{node.tool.qualified || shortTool(node)}</p>
        <p className="text-[12px] text-muted-foreground">
          {kindLabel(node)}, {formatTime(node.timestamp_utc)}
        </p>
      </div>

      {node.tool.command ? (
        <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-all rounded-sm border border-border bg-background p-2.5 font-mono text-[12px] leading-relaxed">
          {node.tool.command}
          {node.tool.command_truncated ? "\n[cut at 4,000 characters]" : ""}
        </pre>
      ) : family.family === "shell" ? (
        <p className="rounded-sm border border-dashed border-border p-2.5 text-[12px] leading-relaxed text-muted-foreground">
          Command text is not recorded. The trail keeps a hash of the arguments; set AGENTMETRY_LOG_COMMANDS=1 to keep the
          command line as well.
        </p>
      ) : null}

      <dl className="grid grid-cols-[7.5rem_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-[12px]">
        <dt className="text-subtle">Branch</dt>
        <dd>{family.label}</dd>
        {node.asked_as && node.asked_as !== node.tool.qualified ? (
          <>
            <dt className="text-subtle">Asked as</dt>
            <dd className="font-mono">{node.asked_as}</dd>
          </>
        ) : null}
        <dt className="text-subtle">Outcome</dt>
        <dd>{node.kind === "denied" ? "denied" : node.outcome || "recorded"}</dd>
        {node.tool.mitre?.technique_id ? (
          <>
            <dt className="text-subtle">ATT&amp;CK</dt>
            <dd>
              <span className="font-mono">{node.tool.mitre.technique_id}</span> {node.tool.mitre.technique}
              {node.tool.mitre.tactic ? <span className="text-muted-foreground"> ({node.tool.mitre.tactic})</span> : null}
            </dd>
          </>
        ) : null}
        {node.tool.input_hash ? (
          <>
            <dt className="text-subtle">Input hash</dt>
            <dd className="truncate font-mono" title={node.tool.input_hash}>
              {node.tool.input_hash.slice(0, 16)}…
            </dd>
          </>
        ) : null}
        <dt className="text-subtle">Events</dt>
        <dd className="font-mono text-[11px]">
          {node.event_ids.map((id) => (
            <span key={id} className="block truncate" title={id}>
              {id}
            </span>
          ))}
        </dd>
      </dl>

      {approval || policy || dlp ? (
        <ul className="space-y-1.5 text-[12px] leading-relaxed text-muted-foreground">
          {approval ? <li>{approval}</li> : null}
          {policy ? <li className="text-caution">{policy}</li> : null}
          {dlp ? <li className="text-caution">{dlp}</li> : null}
        </ul>
      ) : null}
    </div>
  );
}
