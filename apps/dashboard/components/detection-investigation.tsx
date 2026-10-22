"use client";

import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  Activity,
  Ban,
  Bot,
  ChevronDown,
  ChevronRight,
  Clock3,
  ExternalLink,
  FileText,
  GitBranch,
  Globe,
  ListTree,
  Monitor,
  Plug,
  Search,
  ShieldAlert,
  Table2,
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
  session: Clock3,
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
    case "call":
      return node.approval ? "Asked, then ran" : "Tool call";
    case "session_start":
      return "Session started";
    case "session_end":
      return "Session ended";
    default: {
      // The tree endpoint passes any other action type through as the kind.
      // Calling those "Tool call" put session lifecycle rows in the tool lists.
      const words = node.kind.replace(/_/g, " ");
      return words ? words[0].toUpperCase() + words.slice(1) : "Event";
    }
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

const EXPORT_OFF =
  "Session views are off in this install: AGENTMETRY_AUDIT_EXPORT_ENABLED is false, so the server does not return session events.";

/** Said wherever a view draws from a windowed session, not only in Details and the tree. */
function WindowNote({ truncated, total }: { truncated: boolean; total?: number }) {
  if (!truncated) return null;
  return (
    <span className="text-caution">
      A window of a longer session{total ? ` (${total.toLocaleString()} events in all)` : ""}. The event stream has the rest.
    </span>
  );
}

type InvestigationView = "details" | "table" | "tree" | "graph" | "timeline";

const INVESTIGATION_VIEWS: { id: InvestigationView; label: string; description: string; icon: typeof Activity }[] = [
  { id: "details", label: "Details", description: "Why the detection fired: rule summary, cited evidence, and triage.", icon: ShieldAlert },
  { id: "table", label: "Activity table", description: "Search and filter individual recorded events.", icon: Table2 },
  { id: "tree", label: "Activity tree", description: "Follow recorded calls grouped by tool category.", icon: ListTree },
  { id: "graph", label: "Activity graph", description: "See event order across tool categories.", icon: GitBranch },
  { id: "timeline", label: "Events timeline", description: "Read session events in chronological order.", icon: Clock3 },
];

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
  const [view, setView] = useState<InvestigationView>("details");

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
  const activityNodes = useMemo(
    () => (tree ? tree.nodes.filter((node) => node.kind !== "detection") : []),
    [tree],
  );

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
        <div className="flex min-w-[16rem] flex-1 flex-wrap items-center gap-x-3 gap-y-1">
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

      <nav className="panel flex min-w-0 items-stretch overflow-x-auto px-2" role="tablist" aria-label="Detection investigation views">
        {INVESTIGATION_VIEWS.map(({ id, label, icon: Icon }, index) => (
          <button
            key={id}
            id={`investigation-tab-${id}`}
            type="button"
            role="tab"
            aria-selected={view === id}
            aria-controls="detection-view-content"
            tabIndex={view === id ? 0 : -1}
            onClick={() => setView(id)}
            onKeyDown={(event) => {
              const last = INVESTIGATION_VIEWS.length - 1;
              const next =
                event.key === "ArrowRight" ? (index === last ? 0 : index + 1)
                : event.key === "ArrowLeft" ? (index === 0 ? last : index - 1)
                : event.key === "Home" ? 0
                : event.key === "End" ? last
                : null;
              if (next === null) return;
              event.preventDefault();
              setView(INVESTIGATION_VIEWS[next].id);
              document.getElementById(`investigation-tab-${INVESTIGATION_VIEWS[next].id}`)?.focus();
            }}
            className={`relative flex min-h-12 shrink-0 items-center gap-2 border-b-2 px-4 text-[12px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-signal ${
              view === id
                ? "border-signal text-foreground"
                : "border-transparent text-muted-foreground hover:border-border hover:text-foreground"
            }`}
          >
            <Icon className="h-4 w-4" aria-hidden />
            {label}
          </button>
        ))}
      </nav>


      <div className="flex min-h-0 flex-1 flex-col gap-3 xl:flex-row">
        <main id="detection-view-content" role="tabpanel" aria-labelledby={`investigation-tab-${view}`} className="panel flex min-h-[28rem] min-w-0 flex-1 flex-col overflow-hidden" aria-label="Investigation workspace">
          {view === "details" ? (
            <DetectionDetails
              det={det}
              app={app}
              host={host}
              tree={tree}
              citedNodes={citedNodes}
              loading={loading}
              error={error}
              missing={missing}
              onSelect={(id) => {
                setSelectedId(id);
                setView("tree");
              }}
            />
          ) : null}

          {view === "tree" ? (
        <section className="flex min-h-[28rem] min-w-0 flex-1 flex-col overflow-hidden" aria-label="Agent activity tree">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
            <div className="flex min-w-0 items-center gap-2">
              <ListTree className="h-4 w-4 text-muted-foreground" aria-hidden />
              <div className="min-w-0">
              <p className="text-[13px] font-medium">Agent activity tree</p>
                <p className="text-[12px] text-muted-foreground">Recorded tool calls, grouped by activity type. Cited evidence is highlighted.</p>
              </div>
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
                {tree && !tree.enabled ? EXPORT_OFF : "This session is no longer in the trail index."}
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
                      rows={foldBranch(branch, cited, expanded, 2, 3, selected?.id ?? null)}
                      open={
                        !collapsed.has(branch.key) &&
                        (branch.cited > 0 ||
                          branch.flagged > 0 ||
                          expanded.has(`${branch.key}:*`) ||
                          branches.length <= 3 ||
                          branch.nodes.some((node) => node.id === selected?.id))
                      }
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
                <p className="mt-4 text-[12px] leading-relaxed text-subtle">
                  This is an agent activity tree, not an operating-system process tree. Hooks record the calls an
                  agent makes; they do not record child processes launched inside a shell command. Subagents are
                  shown when they start and stop, but the trail cannot attribute each interleaved call to a subagent.
                </p>
              </>
            )}
          </div>
        </section>
          ) : null}

          {view === "table" ? (
            <ActivityTable nodes={activityNodes} cited={cited} selectedId={selected?.id ?? null} onSelect={setSelectedId} truncated={tree?.truncated ?? false} total={tree?.summary.total} />
          ) : null}

          {view === "graph" ? (
            <ActivityGraph nodes={activityNodes} cited={cited} selectedId={selected?.id ?? null} onSelect={setSelectedId} truncated={tree?.truncated ?? false} total={tree?.summary.total} />
          ) : null}

          {view === "timeline" ? (
            <EventsTimeline nodes={activityNodes} cited={cited} selectedId={selected?.id ?? null} onSelect={setSelectedId} truncated={tree?.truncated ?? false} total={tree?.summary.total} />
          ) : null}
        </main>

        <aside className="panel flex min-h-0 w-full shrink-0 flex-col overflow-y-auto xl:w-[26rem]" aria-label="Details">
          <div className="space-y-5 p-4">
            {view !== "details" && selected ? <NodeDetail node={selected} cited={isCited(selected, cited)} /> : null}
            {view !== "details" ? (
              <div className="space-y-2">
                <p className="eyebrow">Why it fired</p>
                <p className="text-[13px] leading-relaxed text-muted-foreground">{det.summary}</p>
                {chain?.length ? <TechniqueChain ids={chain} /> : null}
              </div>
            ) : null}
            {view === "details" && citedNodes.length ? (
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <p className="eyebrow">Evidence cited by this detection</p>
                  <span className="font-mono text-[12px] text-subtle">{citedNodes.length}</span>
                </div>
                <ul className="space-y-1.5">
                  {citedNodes.slice(0, 5).map((node) => (
                    <li key={node.id}>
                      <button
                        type="button"
                        onClick={() => {
                          setSelectedId(node.id);
                          setView("tree");
                        }}
                        className="w-full rounded-sm border border-border px-2.5 py-2 text-left hover:border-danger/50 hover:bg-danger/[0.04]"
                      >
                        <span className="flex items-center justify-between gap-2">
                          <span className="truncate font-mono text-[12px]">{shortTool(node)}</span>
                          <span className="shrink-0 font-mono text-[12px] text-subtle">{clock(node.timestamp_utc)}</span>
                        </span>
                        {node.tool.command ? <span className="mt-1 block truncate font-mono text-[12px] text-muted-foreground">{node.tool.command}</span> : null}
                      </button>
                    </li>
                  ))}
                </ul>
                {citedNodes.length > 5 ? (
                  <button type="button" onClick={() => setView("table")} className="text-[12px] text-signal hover:underline">
                    View all {citedNodes.length} cited events in the activity table
                  </button>
                ) : null}
              </div>
            ) : null}
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

function DetectionDetails({
  det,
  app,
  host,
  tree,
  citedNodes,
  loading,
  error,
  missing,
}: {
  det: Detection;
  app: string;
  host: string;
  tree: SessionTreePayload | null;
  citedNodes: SessionNode[];
  loading: boolean;
  error: string | null;
  missing: string[];
  onSelect: (id: string) => void;
}) {
  const flaggedCount = tree?.nodes.filter(isFlagged).length ?? 0;
  const toolCount = tree?.nodes.filter((node) => node.kind === "call" || node.kind === "denied").length ?? 0;
  const facts = [
    { label: "Detection rule", value: det.rule_id, mono: true },
    { label: "Agent", value: app ? sourceLabel(app) : "Unknown" },
    { label: "Machine", value: host || "Unknown" },
    { label: "First seen", value: formatTime(det.first_seen_utc) },
    { label: "Last seen", value: formatTime(det.last_seen_utc) },
    { label: "Session", value: shortId(det.correlation_id), mono: true },
  ];

  return (
    <div className="min-h-0 flex-1 overflow-auto p-5">
      <div className="mx-auto max-w-5xl space-y-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <span className="raised mt-0.5 inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-md text-danger">
              <ShieldAlert className="h-5 w-5" aria-hidden />
            </span>
            <div>
              <p className="eyebrow">Why it fired</p>
              <p className="mt-1 max-w-3xl text-[16px] font-medium leading-relaxed">{det.summary || "No rule summary was recorded."}</p>
            </div>
          </div>
        </div>

        <dl className="grid gap-px overflow-hidden rounded-sm border border-border bg-border sm:grid-cols-2 xl:grid-cols-3">
          {facts.map((fact) => (
            <div key={fact.label} className="min-w-0 bg-card px-3.5 py-3">
              <dt className="eyebrow">{fact.label}</dt>
              <dd className={`mt-1 truncate text-[13px] ${fact.mono ? "font-mono" : "font-medium"}`} title={fact.value}>{fact.value}</dd>
            </div>
          ))}
        </dl>

        <section className="space-y-3 rounded-sm border border-border bg-background p-4" aria-labelledby="session-summary-heading">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h4 id="session-summary-heading" className="text-[13px] font-semibold">Session evidence</h4>
              <p className="mt-0.5 text-[12px] text-muted-foreground">Recorded events counts the whole session. The other counts cover the events loaded for this investigation.</p>
            </div>
            {tree?.truncated ? <span className="rounded-sm bg-caution/10 px-2 py-1 text-[12px] text-caution">Session view is truncated</span> : null}
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <SummaryMetric label="Recorded events" value={tree?.summary.total ?? (loading ? "…" : "—")} />
            <SummaryMetric label="Tool activity" value={toolCount} />
            <SummaryMetric label="Cited by rule" value={citedNodes.length} tone="danger" />
            <SummaryMetric label="Policy / refusal signals" value={flaggedCount} tone={flaggedCount ? "caution" : undefined} />
          </div>
          {loading ? <p className="text-[12px] text-muted-foreground">Loading session evidence…</p> : null}
          {error ? <p className="text-[12px] text-danger">Could not load session evidence: {error}</p> : null}
          {!loading && !error && (!tree || !tree.nodes.length) ? (
            <p className="text-[12px] text-muted-foreground">
              {tree && !tree.enabled ? EXPORT_OFF : "The session is not available in the current trail index."} Detection metadata is still shown above.
            </p>
          ) : null}
          {missing.length && tree?.nodes.length ? (
            <p className="text-[12px] text-caution">
              {missing.length} of the {(det.event_ids ?? []).length} events this detection cites are not in the trail index.
            </p>
          ) : null}
        </section>

        <div className="flex items-start gap-2 rounded-sm border border-border px-3 py-2.5 text-[12px] leading-relaxed text-muted-foreground">
          <Activity className="mt-0.5 h-3.5 w-3.5 shrink-0 text-signal" aria-hidden />
          This investigation reconstructs recorded agent tool activity. Agentmetry does not currently collect host process IDs or parent/child process ancestry, so the tree and graph below are session activity views rather than operating-system process views.
        </div>

        {tree?.summary.first_utc && tree.summary.last_utc ? (
          <p className="inline-flex items-center gap-1.5 text-[12px] text-subtle">
            <Clock3 className="h-3 w-3" aria-hidden />
            Session window: {formatTime(tree.summary.first_utc)} to {formatTime(tree.summary.last_utc)}
          </p>
        ) : null}
      </div>
    </div>
  );
}

function SummaryMetric({ label, value, tone }: { label: string; value: number | string; tone?: "danger" | "caution" }) {
  return (
    <div className="rounded-sm border border-border bg-card px-3 py-2.5">
      <p className="font-mono text-[19px] font-semibold leading-none">{value}</p>
      <p className={`mt-1.5 text-[12px] ${tone === "danger" ? "text-danger" : tone === "caution" ? "text-caution" : "text-muted-foreground"}`}>{label}</p>
    </div>
  );
}

function ActivityTable({
  nodes,
  cited,
  selectedId,
  onSelect,
  truncated,
  total,
}: {
  nodes: SessionNode[];
  cited: Set<string>;
  selectedId: string | null;
  onSelect: (id: string) => void;
  truncated: boolean;
  total?: number;
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"all" | "cited" | "flagged">("all");
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return nodes.filter((node) => {
      if (filter === "cited" && !isCited(node, cited)) return false;
      if (filter === "flagged" && !isFlagged(node)) return false;
      if (!needle) return true;
      return [shortTool(node), node.tool.qualified, node.tool.command, node.app, node.reason, node.kind, node.outcome]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(needle);
    });
  }, [nodes, cited, filter, query]);

  return (
    <section className="flex min-h-0 flex-1 flex-col" aria-label="Recorded agent activity table">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div>
          <h3 className="text-[13px] font-semibold">Recorded activity</h3>
          <p className="mt-0.5 text-[12px] text-muted-foreground">Select a row to inspect its evidence and policy context.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-subtle" aria-hidden />
            <input value={query} onChange={(event) => setQuery(event.target.value)} className="h-8 w-48 rounded-sm border border-border bg-background pl-8 pr-2 text-[12px] outline-none focus:border-signal" placeholder="Filter activity" aria-label="Filter activity" />
          </label>
          <div className="flex rounded-sm border border-border p-0.5" aria-label="Activity filters">
            {(["all", "cited", "flagged"] as const).map((value) => (
              <button key={value} type="button" aria-pressed={filter === value} onClick={() => setFilter(value)} className={`rounded-sm px-2 py-1 text-[12px] capitalize ${filter === value ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground"}`}>
                {value}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full min-w-[640px] border-collapse text-left text-[12px]">
          <thead className="sticky top-0 z-10 bg-background text-[12px] uppercase tracking-wide text-subtle">
            <tr className="border-b border-border">
              <th className="px-3 py-2 font-medium">Time</th>
              <th className="px-3 py-2 font-medium">Signal</th>
              <th className="px-3 py-2 font-medium">Activity</th>
              <th className="px-3 py-2 font-medium">Agent / tool</th>
              <th className="px-3 py-2 font-medium">Recorded input</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((node) => {
              const citedHere = isCited(node, cited);
              const signal = citedHere ? "Cited evidence" : isFlagged(node) ? node.kind === "denied" ? "Refused" : node.dlp?.rule_id ? "DLP match" : "Policy match" : node.outcome || "Recorded";
              return (
                <tr
                  key={node.id}
                  tabIndex={0}
                  role="button"
                  aria-pressed={node.id === selectedId}
                  onClick={() => onSelect(node.id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      onSelect(node.id);
                    }
                  }}
                  className={`cursor-pointer border-b border-border/70 transition-colors hover:bg-muted/60 focus:bg-muted/60 focus:outline-none ${node.id === selectedId ? "bg-signal/[0.07]" : citedHere ? "bg-danger/[0.035]" : ""}`}
                >
                  <td className="whitespace-nowrap px-3 py-2.5 font-mono text-muted-foreground">{clock(node.timestamp_utc)}</td>
                  <td className="whitespace-nowrap px-3 py-2.5"><span className={`rounded-sm px-1.5 py-0.5 text-[12px] ${citedHere ? "bg-danger/10 text-danger" : isFlagged(node) ? "bg-caution/10 text-caution" : "text-muted-foreground"}`}>{signal}</span></td>
                  <td className="px-3 py-2.5">
                    <span className="block font-mono text-[12px] font-medium text-foreground">{shortTool(node)}</span>
                    <span className="block text-[12px] text-subtle">{kindLabel(node)}</span>
                  </td>
                  <td className="px-3 py-2.5 text-muted-foreground">{sourceLabel(node.app) || node.app || "Unknown"}</td>
                  <td className="max-w-[20rem] px-3 py-2.5 font-mono text-muted-foreground"><span className="block truncate" title={node.tool.command || node.reason}>{node.tool.command || node.reason || "—"}</span></td>
                </tr>
              );
            })}
            {!filtered.length ? <tr><td colSpan={5} className="px-4 py-12 text-center text-muted-foreground">No recorded activity matches this filter.</td></tr> : null}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-4 py-2 text-[12px] text-subtle">
        <span>Showing {filtered.length.toLocaleString()} of {nodes.length.toLocaleString()} recorded events · select a row to update the details panel</span>
        <WindowNote truncated={truncated} total={total} />
      </div>
    </section>
  );
}

function ActivityGraph({
  nodes,
  cited,
  selectedId,
  onSelect,
  truncated,
  total,
}: {
  nodes: SessionNode[];
  cited: Set<string>;
  selectedId: string | null;
  onSelect: (id: string) => void;
  truncated: boolean;
  total?: number;
}) {
  const [showAll, setShowAll] = useState(false);
  const ordered = useMemo(() => [...nodes].sort((a, b) => a.timestamp_utc.localeCompare(b.timestamp_utc)), [nodes]);
  const visible = useMemo(() => {
    if (!ordered.length) return [];
    const keep = new Set<number>();
    if (showAll) {
      for (let i = 0; i < Math.min(ordered.length, 80); i += 1) keep.add(i);
    } else {
      ordered.forEach((node, index) => {
        if (isCited(node, cited) || isFlagged(node)) {
          for (let i = Math.max(0, index - 1); i <= Math.min(ordered.length - 1, index + 1); i += 1) keep.add(i);
        }
      });
      if (!keep.size) for (let i = 0; i < Math.min(ordered.length, 18); i += 1) keep.add(i);
    }
    const shown = [...keep].sort((a, b) => a - b).slice(0, 80);
    // Picked in another view, the selection must still be on the graph.
    const selectedIndex = ordered.findIndex((node) => node.id === selectedId);
    if (selectedIndex >= 0 && !shown.includes(selectedIndex)) shown.push(selectedIndex);
    return shown.sort((a, b) => a - b).map((index) => ordered[index]);
  }, [ordered, cited, showAll, selectedId]);
  const lanes = useMemo(() => {
    const map = new Map<string, { label: string; family: Family }>();
    for (const node of visible) {
      const family = toolFamily(node);
      if (!map.has(family.key)) map.set(family.key, { label: family.label, family: family.family });
    }
    return [...map.entries()];
  }, [visible]);

  const stepX = 184;
  const laneY = 106;
  const left = 148;
  const graphWidth = Math.max(760, left + visible.length * stepX + 20);
  const graphHeight = Math.max(220, lanes.length * laneY + 42);
  const positions = visible.map((node, index) => {
    const key = toolFamily(node).key;
    const lane = Math.max(0, lanes.findIndex(([laneKey]) => laneKey === key));
    return { node, x: left + index * stepX, y: 30 + lane * laneY, lane };
  });

  return (
    <section className="flex min-h-0 flex-1 flex-col" aria-label="Recorded session activity graph">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div>
          <h3 className="text-[13px] font-semibold">Session activity graph</h3>
          <p className="mt-0.5 text-[12px] text-muted-foreground">Nodes are recorded agent actions. Connectors show event order, not operating-system parent/child relationships.</p>
        </div>
        <button type="button" className="btn" aria-pressed={showAll} onClick={() => setShowAll((value) => !value)}>
          {showAll ? "Focus on signals" : `Show all activity${ordered.length > 80 ? " (first 80)" : ""}`}
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto bg-background p-4" style={{ backgroundImage: "radial-gradient(hsl(var(--border) / 0.45) 0.65px, transparent 0.65px)", backgroundSize: "18px 18px" }}>
        {!visible.length ? <p className="py-12 text-center text-[12px] text-muted-foreground">No session activity is available for this detection.</p> : (
          <div className="relative" style={{ width: graphWidth, height: graphHeight }}>
            <svg className="pointer-events-none absolute inset-0 overflow-visible" width={graphWidth} height={graphHeight} aria-hidden="true">
              <defs>
                <marker id="session-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
                  <path d="M0,0 L7,3.5 L0,7" className="fill-none stroke-subtle" strokeWidth="1.2" />
                </marker>
              </defs>
              {positions.slice(0, -1).map((position, index) => {
                const next = positions[index + 1];
                return <line key={`${position.node.id}-${next.node.id}`} x1={position.x + 78} y1={position.y + 66} x2={next.x + 78} y2={next.y + 66} className="stroke-border" strokeWidth="1.5" markerEnd="url(#session-arrow)" />;
              })}
              {lanes.map(([key], index) => <line key={key} x1={left - 12} y1={30 + index * laneY + 90} x2={graphWidth - 16} y2={30 + index * laneY + 90} className="stroke-border/60" strokeDasharray="3 5" />)}
            </svg>
            {lanes.map(([key, lane], index) => {
              const Icon = FAMILY_ICON[lane.family];
              return <div key={key} className="absolute left-0 flex w-[126px] items-center gap-1.5 truncate rounded-sm border border-border bg-card/90 px-2 py-1.5 text-[12px] font-medium text-muted-foreground" style={{ top: 30 + index * laneY + 7 }} title={lane.label}><Icon className="h-3 w-3 shrink-0" aria-hidden />{lane.label}</div>;
            })}
            {positions.map(({ node, x, y }) => {
              const citedHere = isCited(node, cited);
              const flaggedHere = isFlagged(node);
              return (
                <button
                  key={node.id}
                  type="button"
                  aria-pressed={selectedId === node.id}
                  onClick={() => onSelect(node.id)}
                  className={`absolute w-[156px] rounded-sm border px-2.5 py-2 text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-md ${selectedId === node.id ? "z-10 border-signal ring-2 ring-signal/40" : citedHere ? "border-danger/60 bg-danger/[0.08]" : flaggedHere ? "border-caution/50 bg-caution/[0.07]" : "border-border bg-card/95 hover:border-foreground/30"}`}
                  style={{ left: x, top: y }}
                  title={node.tool.command || node.reason || shortTool(node)}
                >
                  <span className="flex items-center justify-between gap-1">
                    <span className="truncate font-mono text-[12px] font-semibold">{shortTool(node)}</span>
                    {citedHere ? <ShieldAlert className="h-3 w-3 shrink-0 text-danger" aria-label="Cited evidence" /> : flaggedHere ? <ShieldAlert className="h-3 w-3 shrink-0 text-caution" aria-label="Policy or refusal signal" /> : null}
                  </span>
                  <span className="mt-1 block truncate font-mono text-[11px] text-subtle">{clock(node.timestamp_utc)}</span>
                  <span className="mt-1 block truncate font-mono text-[11px] text-muted-foreground">{node.tool.command || kindLabel(node)}</span>
                </button>
              );
            })}
          </div>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-4 border-t border-border px-4 py-2 text-[12px] text-muted-foreground">
        <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-danger" /> Cited evidence</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-caution" /> Refusal or policy signal</span>
        <WindowNote truncated={truncated} total={total} />
        <span className="ml-auto">{visible.length} of {ordered.length} events · select a node to inspect it</span>
      </div>
    </section>
  );
}

function EventsTimeline({
  nodes,
  cited,
  selectedId,
  onSelect,
  truncated,
  total,
}: {
  nodes: SessionNode[];
  cited: Set<string>;
  selectedId: string | null;
  onSelect: (id: string) => void;
  truncated: boolean;
  total?: number;
}) {
  const pageSize = 100;
  const ordered = useMemo(() => [...nodes].sort((a, b) => a.timestamp_utc.localeCompare(b.timestamp_utc)), [nodes]);
  const citedIndex = useMemo(() => ordered.findIndex((node) => isCited(node, cited)), [ordered, cited]);
  const maxStart = Math.max(0, ordered.length - pageSize);
  const initialStart = Math.max(0, Math.min(maxStart, citedIndex >= 0 ? citedIndex - Math.floor(pageSize / 2) : maxStart));
  const [start, setStart] = useState(initialStart);

  useEffect(() => setStart(initialStart), [initialStart]);

  const visible = ordered.slice(start, start + pageSize);
  const end = Math.min(start + visible.length, ordered.length);

  return (
    <section className="flex min-h-0 flex-1 flex-col" aria-label="Events timeline">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div>
          <h3 className="text-[13px] font-semibold">Events timeline</h3>
          <p className="mt-0.5 text-[12px] text-muted-foreground">Recorded session events in time order. Events cited by the detection are highlighted.</p>
        </div>
        <span className="font-mono text-[12px] text-muted-foreground">{ordered.length.toLocaleString()} events</span>
      </div>
      <div className="min-h-0 flex-1 overflow-auto px-4 py-3">
        {!visible.length ? (
          <p className="py-12 text-center text-[12px] text-muted-foreground">No session events are available for this detection.</p>
        ) : (
          <ol className="ml-2 border-l border-border pl-5">
            {visible.map((node) => {
              const citedHere = isCited(node, cited);
              const flaggedHere = isFlagged(node);
              const signal = citedHere ? "Cited evidence" : flaggedHere ? node.kind === "denied" ? "Refused" : node.dlp?.rule_id ? "DLP match" : "Policy match" : null;
              return (
                <li key={node.id} className="relative pb-2.5 last:pb-0">
                  <span className={`absolute -left-[1.57rem] top-4 h-2 w-2 rounded-full ring-4 ring-background ${citedHere ? "bg-danger" : flaggedHere ? "bg-caution" : "bg-subtle"}`} aria-hidden />
                  <button
                    type="button"
                    aria-pressed={selectedId === node.id}
                    onClick={() => onSelect(node.id)}
                    className={`w-full rounded-sm border px-3 py-2 text-left transition-colors hover:border-foreground/30 hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal ${selectedId === node.id ? "border-signal bg-signal/[0.07]" : citedHere ? "border-danger/40 bg-danger/[0.035]" : flaggedHere ? "border-caution/40 bg-caution/[0.035]" : "border-border bg-card"}`}
                  >
                    <span className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                      <span className="flex min-w-0 items-center gap-2">
                        <span className="truncate font-mono text-[12px] font-medium">{shortTool(node)}</span>
                        {signal ? <span className={`shrink-0 rounded-sm px-1.5 py-0.5 text-[12px] ${citedHere ? "bg-danger/10 text-danger" : "bg-caution/10 text-caution"}`}>{signal}</span> : null}
                      </span>
                      <time dateTime={node.timestamp_utc} className="shrink-0 font-mono text-[12px] text-subtle">{clock(node.timestamp_utc)}</time>
                    </span>
                    <span className="mt-1 block text-[12px] text-muted-foreground">{sourceLabel(node.app) || node.app || "Unknown agent"} · {kindLabel(node)}</span>
                    <span className="mt-1 block truncate font-mono text-[12px] text-subtle" title={node.tool.command || node.reason || undefined}>{node.tool.command || node.reason || "No input detail recorded"}</span>
                  </button>
                </li>
              );
            })}
          </ol>
        )}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-4 py-2">
        <span className="text-[12px] text-subtle">
          Showing {ordered.length ? `${(start + 1).toLocaleString()}–${end.toLocaleString()}` : "0"} of {ordered.length.toLocaleString()} events{" "}
          <WindowNote truncated={truncated} total={total} />
        </span>
        <div className="flex items-center gap-2">
          <button type="button" className="btn" onClick={() => setStart((value) => Math.max(0, value - pageSize))} disabled={start === 0}>Previous 100</button>
          <button type="button" className="btn" onClick={() => setStart((value) => Math.min(maxStart, value + pageSize))} disabled={start >= maxStart}>Next 100</button>
        </div>
      </div>
    </section>
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
      <div className="mt-1 flex items-center justify-between gap-3 font-mono text-[12px] text-subtle">
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
        {sub ? <p className="truncate font-mono text-[12px] text-subtle">{sub}</p> : null}
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
        <span className="font-mono text-[12px] text-muted-foreground">
          {branch.nodes.length.toLocaleString()} {branch.nodes.length === 1 ? "call" : "calls"}
        </span>
        {branch.cited ? (
          <span className="inline-flex items-center gap-1 rounded-sm bg-danger/10 px-1.5 py-px font-mono text-[12px] text-danger">
            <ShieldAlert className="h-3 w-3" aria-hidden /> {branch.cited} cited
          </span>
        ) : null}
        {branch.flagged ? (
          <span className="rounded-sm bg-caution/10 px-1.5 py-px font-mono text-[12px] text-caution">{branch.flagged} flagged</span>
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
                  className="w-full rounded-sm border border-dashed border-border px-3 py-1.5 text-left font-mono text-[12px] text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground"
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
            {cited ? <span className="rounded-sm bg-danger/15 px-1 py-px font-mono text-[12px] uppercase tracking-wide text-danger">cited</span> : null}
            {denied ? <span className="rounded-sm bg-caution/15 px-1 py-px font-mono text-[12px] uppercase tracking-wide text-caution">denied</span> : null}
            {error ? <span className="rounded-sm bg-danger/10 px-1 py-px font-mono text-[12px] uppercase tracking-wide text-danger">error</span> : null}
            {node.tool_policy?.rule_id ? <span className="rounded-sm bg-caution/10 px-1 py-px font-mono text-[12px] text-caution">policy</span> : null}
            {node.dlp?.rule_id ? <span className="rounded-sm bg-caution/10 px-1 py-px font-mono text-[12px] text-caution">dlp</span> : null}
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
        <span className="shrink-0 font-mono text-[12px] text-subtle">{clock(node.timestamp_utc)}</span>
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
          <span className="inline-flex items-center gap-1 rounded-sm bg-danger/10 px-1.5 py-px font-mono text-[12px] text-danger">
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
        <dt className="text-subtle">Category</dt>
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
        <dd className="font-mono text-[12px]">
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
