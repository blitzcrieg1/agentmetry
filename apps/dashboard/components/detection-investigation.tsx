"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeft, ChevronRight, Clock3, GitBranch, ListTree, Maximize2, Minimize2, ShieldAlert, Table2 } from "lucide-react";
import type { Detection } from "@/components/flight-recorder-panel";
import { SeverityBadge } from "@/components/ui/kit";
import { StatusChip, formatTime } from "@/components/triage-panel";
import { ActivityCanvas } from "@/components/investigation/activity-canvas";
import { ActivityTable } from "@/components/investigation/activity-table";
import { DetectionDetails, EXPORT_OFF } from "@/components/investigation/details";
import { Drawer, type DrawerContext } from "@/components/investigation/drawer";
import { EventsTimeline } from "@/components/investigation/events-timeline";
import { Legend } from "@/components/investigation/legend";
import { type Disposition, statusOf } from "@/lib/disposition";
import { sourceLabel } from "@/lib/audit-source";
import {
  type Entity,
  type Highlight,
  buildHierarchy,
  familyCounts,
  layoutHorizontal,
  layoutVertical,
  matchesHighlight,
} from "@/lib/investigation";
import { type SessionTreePayload, citedSet, fetchSessionTree, isCited, isFlagged, toolFamily } from "@/lib/session-tree";

type View = "details" | "table" | "tree" | "graph" | "timeline";

const VIEWS: { id: View; label: string; icon: typeof ShieldAlert }[] = [
  { id: "details", label: "Details", icon: ShieldAlert },
  { id: "table", label: "Activity table", icon: Table2 },
  { id: "tree", label: "Activity tree", icon: ListTree },
  { id: "graph", label: "Activity graph", icon: GitBranch },
  { id: "timeline", label: "Events timeline", icon: Clock3 },
];

type Focus = { type: "call"; id: string } | { type: "entity"; entity: Entity } | null;

/**
 * A detection opened as an investigation: Details to decide, then a table, a
 * tree, a graph and a timeline of the same session to dig. All four share one
 * selection, a legend on the left that hides and highlights, and a panel on the
 * right with the selected call and the triage form.
 *
 * The tree is agent tool activity: machine, agent, session, tool category,
 * call. The hooks never see the operating system's process table, so no level
 * of it is a parent process, and every view says so.
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
  const [view, setView] = useState<View>("details");
  const [focus, setFocus] = useState<Focus>(null);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [highlight, setHighlight] = useState<Highlight | null>(null);
  const [legendCollapsed, setLegendCollapsed] = useState(false);
  const [drawerCollapsed, setDrawerCollapsed] = useState(false);

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
  const nodes = useMemo(() => tree?.nodes ?? [], [tree]);
  const activity = useMemo(() => nodes.filter((n) => n.kind !== "detection"), [nodes]);
  const citedNodes = useMemo(() => activity.filter((n) => isCited(n, cited)), [activity, cited]);
  const detectionsInSession = useMemo(() => nodes.filter((n) => n.kind === "detection"), [nodes]);
  const families = useMemo(() => familyCounts(activity, cited), [activity, cited]);
  const shownFamilies = useMemo(() => families.filter((f) => !hidden.has(f.key)), [families, hidden]);
  const shownActivity = useMemo(() => activity.filter((n) => !hidden.has(toolFamily(n).key)), [activity, hidden]);

  // The agent is the one that made the cited call. A session also carries
  // Agentmetry's own events, and `summary.apps` is alphabetical, so taking its
  // first entry named the recorder as the agent.
  const app = useMemo(() => {
    if (citedNodes[0]?.app) return citedNodes[0].app;
    const counts = new Map<string, number>();
    for (const n of activity) if (n.app) counts.set(n.app, (counts.get(n.app) ?? 0) + 1);
    return [...counts].sort((a, b) => b[1] - a[1])[0]?.[0] ?? det.app ?? "";
  }, [citedNodes, activity, det.app]);
  const appLabel = app ? sourceLabel(app) : "";
  const host = tree?.summary.hosts?.[0] ?? "";
  const missing = (det.event_ids ?? []).filter((id) => !nodes.some((n) => n.event_ids.includes(id)));

  // Open on the first cited call, the way an EDR opens on the process that fired.
  const selected = useMemo(() => {
    if (focus?.type === "entity") return null;
    const id = focus?.type === "call" ? focus.id : citedNodes[0]?.id;
    return activity.find((n) => n.id === id) ?? null;
  }, [focus, citedNodes, activity]);

  const hierarchy = useMemo(
    () =>
      buildHierarchy(activity, cited, {
        host,
        app,
        appLabel,
        adapter: citedNodes[0]?.adapter ?? activity[0]?.adapter ?? "",
        sessionId: det.correlation_id,
        hidden,
        expanded,
        selectedId: selected?.id ?? null,
      }),
    [activity, cited, host, app, appLabel, citedNodes, det.correlation_id, hidden, expanded, selected],
  );
  const placedTree = useMemo(() => layoutHorizontal(hierarchy), [hierarchy]);
  const placedGraph = useMemo(() => layoutVertical(hierarchy), [hierarchy]);
  const layoutKey = `${[...hidden].sort().join(",")}|${[...expanded].sort().join(",")}`;
  const isDimmed = useCallback(
    (e: Entity) => Boolean(highlight && e.kind === "call" && e.node && !matchesHighlight(e.node, cited, highlight)),
    [highlight, cited],
  );
  const highlightCounts = useMemo(
    () => ({
      cited: citedNodes.length,
      flagged: activity.filter(isFlagged).length,
      errors: activity.filter((n) => n.outcome === "error").length,
    }),
    [citedNodes, activity],
  );

  const selectCall = (id: string) => setFocus({ type: "call", id });
  const onCanvasSelect = (entity: Entity) => (entity.kind === "call" ? selectCall(entity.id) : setFocus({ type: "entity", entity }));
  const allExpanded = families.length > 0 && families.every((f) => expanded.has(f.key));
  const toggleExpandAll = () => setExpanded(allExpanded ? new Set() : new Set(families.map((f) => f.key)));

  const ctx: DrawerContext = {
    det,
    disposition,
    onDispositionSaved,
    onOpenInStream,
    host,
    sessionId: det.correlation_id,
    cited,
    detectionsInSession,
    families,
  };

  const body = loading ? (
    <p className="m-auto py-16 text-[13px] text-muted-foreground">Loading the session…</p>
  ) : error ? (
    <p className="m-auto py-16 text-[13px] text-danger">{error}</p>
  ) : !activity.length ? (
    <p className="m-auto max-w-md py-16 text-center text-[13px] text-muted-foreground">
      {tree && !tree.enabled ? EXPORT_OFF : "This session is no longer in the trail index."}
    </p>
  ) : null;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <header className="panel flex flex-wrap items-center gap-x-3 gap-y-2 px-3 py-2">
        <button type="button" onClick={onClose} className="btn h-8">
          <ArrowLeft className="h-3.5 w-3.5" /> All detections
        </button>
        <nav className="flex min-w-0 items-center gap-1.5 text-[12px] text-muted-foreground" aria-label="Breadcrumb">
          <span>Detections</span>
          <ChevronRight className="h-3.5 w-3.5" aria-hidden />
          <span className="font-mono">{formatTime(det.first_seen_utc)}</span>
        </nav>
        <div className="flex min-w-[16rem] flex-1 flex-wrap items-center justify-end gap-2">
          <SeverityBadge severity={det.severity} />
          <span className="min-w-0 truncate text-[13px] font-semibold" title={det.title || det.rule_id}>{det.title || det.rule_id}</span>
          <StatusChip status={statusOf(disposition)} />
        </div>
      </header>

      <nav className="flex justify-center overflow-x-auto border-b border-border" role="tablist" aria-label="Investigation views">
        {VIEWS.map(({ id, label, icon: Icon }, index) => (
          <button
            key={id}
            id={`investigation-tab-${id}`}
            type="button"
            role="tab"
            aria-selected={view === id}
            aria-controls="investigation-view"
            tabIndex={view === id ? 0 : -1}
            onClick={() => setView(id)}
            onKeyDown={(event) => {
              const last = VIEWS.length - 1;
              const next =
                event.key === "ArrowRight" ? (index === last ? 0 : index + 1)
                : event.key === "ArrowLeft" ? (index === 0 ? last : index - 1)
                : event.key === "Home" ? 0
                : event.key === "End" ? last
                : null;
              if (next === null) return;
              event.preventDefault();
              setView(VIEWS[next].id);
              document.getElementById(`investigation-tab-${VIEWS[next].id}`)?.focus();
            }}
            className={`flex min-h-11 shrink-0 items-center gap-2 border-b-2 px-5 text-[13px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-signal ${
              view === id ? "border-signal text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            <Icon className="h-4 w-4" aria-hidden />
            {label}
          </button>
        ))}
      </nav>

      <div id="investigation-view" role="tabpanel" aria-labelledby={`investigation-tab-${view}`} className="flex min-h-0 flex-1 flex-col">
        {view === "details" ? (
          <div className="panel flex min-h-0 flex-1 flex-col">
            <DetectionDetails
              det={det}
              app={app}
              host={host}
              tree={tree}
              loading={loading}
              error={error}
              citedNodes={citedNodes}
              families={families}
              missing={missing}
              disposition={disposition}
              onDispositionSaved={onDispositionSaved}
              onInspect={(id) => {
                selectCall(id);
                setView("tree");
              }}
              onInvestigate={() => setView("tree")}
              onOpenInStream={onOpenInStream}
            />
          </div>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col gap-3 xl:flex-row">
            <div className="hidden xl:flex">
              <Legend
                collapsed={legendCollapsed}
                onCollapse={setLegendCollapsed}
                detections={detectionsInSession.length || 1}
                host={host}
                agent={appLabel}
                families={families}
                hidden={hidden}
                onToggle={(key) =>
                  setHidden((prev) => {
                    const next = new Set(prev);
                    if (next.has(key)) next.delete(key);
                    else next.add(key);
                    return next;
                  })
                }
                highlight={highlight}
                onHighlight={setHighlight}
                highlightCounts={highlightCounts}
              />
            </div>

            <main className="panel flex min-h-[32rem] min-w-0 flex-1 flex-col overflow-hidden">
              {body ?? (
                <>
                  {view === "tree" || view === "graph" ? (
                    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
                      <p className="text-[12px] text-muted-foreground">
                        {view === "tree"
                          ? "Machine, agent, session, tool category, call. Select a call to inspect it; open \"more\" to draw a category whole."
                          : "The same session as a graph. Drag to rearrange, scroll to zoom, select a call to inspect it."}
                      </p>
                      <button type="button" className="btn h-8 text-[12px]" onClick={toggleExpandAll} aria-pressed={allExpanded}>
                        {allExpanded ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
                        {allExpanded ? "Fold to the evidence" : "Draw every call"}
                      </button>
                    </div>
                  ) : null}
                  {view === "tree" ? (
                    <ActivityCanvas
                      placed={placedTree}
                      app={app}
                      orientation="horizontal"
                      selectedId={selected?.id ?? (focus?.type === "entity" ? focus.entity.id : null)}
                      isDimmed={isDimmed}
                      onSelect={onCanvasSelect}
                      onExpand={(key) => setExpanded((prev) => new Set(prev).add(key))}
                      layoutKey={`tree|${layoutKey}`}
                    />
                  ) : null}
                  {view === "graph" ? (
                    <ActivityCanvas
                      placed={placedGraph}
                      app={app}
                      orientation="vertical"
                      selectedId={selected?.id ?? (focus?.type === "entity" ? focus.entity.id : null)}
                      isDimmed={isDimmed}
                      onSelect={onCanvasSelect}
                      onExpand={(key) => setExpanded((prev) => new Set(prev).add(key))}
                      layoutKey={`graph|${layoutKey}`}
                    />
                  ) : null}
                  {view === "table" ? (
                    <ActivityTable
                      app={app}
                      appLabel={appLabel}
                      families={shownFamilies}
                      cited={cited}
                      selectedId={selected?.id ?? null}
                      onSelect={selectCall}
                      truncated={tree?.truncated ?? false}
                      total={tree?.summary.total}
                    />
                  ) : null}
                  {view === "timeline" ? (
                    <EventsTimeline
                      nodes={shownActivity}
                      cited={cited}
                      selected={selected}
                      onSelect={selectCall}
                      truncated={tree?.truncated ?? false}
                      total={tree?.summary.total}
                    />
                  ) : null}
                  {(view === "tree" || view === "graph") && tree?.truncated ? (
                    <p className="border-t border-border px-4 py-2 text-[12px] text-caution">
                      A window of a longer session{tree.summary.total ? ` (${tree.summary.total.toLocaleString()} events in all)` : ""}. The event stream has the rest.
                    </p>
                  ) : null}
                  {(view === "tree" || view === "graph") && missing.length ? (
                    <p className="border-t border-border px-4 py-2 text-[12px] text-caution">
                      {missing.length} of the events this detection cites are not in the trail index.
                    </p>
                  ) : null}
                </>
              )}
            </main>

            <Drawer collapsed={drawerCollapsed} onCollapse={setDrawerCollapsed} selected={selected} entity={focus?.type === "entity" ? focus.entity : null} ctx={ctx} />
          </div>
        )}
      </div>
    </div>
  );
}
