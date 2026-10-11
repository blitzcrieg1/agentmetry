"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Play,
  Search,
  ShieldAlert,
  ShieldCheck,
  Square,
  Wrench,
  XCircle,
  Settings2, ArrowUp, ArrowDown, Eye, EyeOff, RefreshCw
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useAgentStore } from "@/lib/store";
import {
  FEED_FOCUS_LABELS,
  FEED_FOCUS_SINCE_MINUTES,
  eventMatchesFocus,
  outcomeFiltersForFocus,
  tailFocusParam,
  type FeedFocusKind,
} from "@/lib/feed-focus";
import { ORCHESTRATOR_URL } from "@/lib/utils";
import { apiHeaders } from "@/lib/api";
import {
  ALL_SOURCE_APPS,
  eventSourceApp,
  sourceDotClass,
  sourceLabel,
} from "@/lib/audit-source";
import { EmptyState, Segmented, Technique } from "@/components/ui/kit";
import { DetectionsStrip } from "@/components/detections-strip";
import { EventHistogram } from "@/components/event-histogram";
import { EventInspector } from "@/components/event-inspector";
import { downloadAuditCsv, downloadAuditJsonl } from "@/lib/audit-export";

export interface AuditEvent {
  event_id?: string;
  schema_version?: string;
  correlation_id?: string;
  timestamp_utc?: string;
  host_id?: string;
  source_topic?: string;
  action?: { type?: string; outcome?: string; reason?: string };
  tool?: { name?: string; qualified?: string; server?: string; input_hash?: string; command?: string; arguments?: Record<string, unknown>; mitre?: { tactic: string; technique: string; tactic_id?: string; technique_id?: string } };
  agent?: { name?: string; skill_id?: string };
  source?: { app?: string; tier?: string; adapter?: string };
  actor?: { type?: string; id?: string; role?: string };
  initiator?: { actor_type?: string; trigger?: string; operator_id?: string };
  model?: { id?: string; provider?: string };
  mcp?: { server_id?: string; tools?: string[] };
  dlp?: { rule_id?: string; mode?: string; pattern_type?: string };
  tool_policy?: { rule_id?: string; action?: string; mode?: string; blocked?: boolean };
  detection?: Detection;
}

export interface Detection {
  rule_id: string;
  title: string;
  severity: "critical" | "high" | "medium" | "low";
  summary: string;
  correlation_id: string;
  tactic_ids: string[];
  technique_ids: string[];
  event_ids: string[];
  first_seen_utc: string;
  last_seen_utc: string;
}

const EVENT_TYPES = [
  "session_start",
  "session_end",
  "tool_called",
  "approval_request",
  "approval_response",
  "detection",
  "detection_disposition",
] as const;

const TIME_WINDOWS: { label: string; minutes: number | null; limit: number }[] = [
  { label: "15m", minutes: 15, limit: 100 },
  { label: "1h", minutes: 60, limit: 150 },
  { label: "6h", minutes: 360, limit: 200 },
  { label: "24h", minutes: 1440, limit: 300 },
  { label: "All", minutes: null, limit: 500 },
];

interface AuditPagination {
  has_older: boolean;
  has_newer: boolean;
  oldest_utc?: string | null;
  newest_utc?: string | null;
  count?: number;
}

function eventKey(event: AuditEvent): string {
  return event.event_id ?? `${event.correlation_id ?? ""}-${event.timestamp_utc ?? ""}`;
}

function sortEvents(events: AuditEvent[]): AuditEvent[] {
  return [...events].sort((a, b) => (a.timestamp_utc ?? "").localeCompare(b.timestamp_utc ?? ""));
}

function mergeEvents(
  existing: AuditEvent[],
  incoming: AuditEvent[],
  mode: "prepend" | "append" | "replace",
): AuditEvent[] {
  if (mode === "replace") return sortEvents(incoming);
  const ordered = mode === "prepend" ? [...incoming, ...existing] : [...existing, ...incoming];
  const byKey = new Map<string, AuditEvent>();
  for (const ev of ordered) byKey.set(eventKey(ev), ev);
  return sortEvents(Array.from(byKey.values()));
}

function SourceBadge({ app }: { app: string }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5 text-[12px] text-muted-foreground">
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${sourceDotClass(app)}`} />
      <span className="truncate">{sourceLabel(app)}</span>
    </span>
  );
}

const ACTION_ICONS: Record<string, LucideIcon> = {
  session_start: Play,
  session_end: Square,
  tool_called: Wrench,
  approval_request: ShieldAlert,
  approval_response: ShieldCheck,
};

function formatTime(ts?: string): string {
  if (!ts) return "—";
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return ts.slice(11, 19) || "—";
  }
}

function outcomeDot(outcome?: string): string {
  switch (outcome) {
    case "success":
      return "bg-secure";
    case "critical": // detection severity
      return "bg-danger";
    case "high":
      return "bg-signal";
    case "medium": // detection severity
      return "bg-caution";
    case "denied":
    case "error":
      return "bg-danger";
    case "pending":
      return "bg-caution animate-pulse";
    default:
      return "bg-subtle";
  }
}

function rowOutcomeClass(outcome?: string, highlight?: boolean): string {
  if (highlight) return "bg-signal/[0.06]";
  switch (outcome) {
    case "critical":
      return "bg-danger/[0.07] shadow-[inset_2px_0_0_hsl(var(--danger))]";
    case "high":
      return "bg-signal/[0.06] shadow-[inset_2px_0_0_hsl(var(--signal))]";
    case "medium":
      return "bg-caution/[0.06] shadow-[inset_2px_0_0_hsl(var(--caution))]";
    case "denied":
    case "error":
      return "bg-danger/[0.04]";
    default:
      return "";
  }
}

function eventSearchHaystack(event: AuditEvent): string {
  const args = event.tool?.arguments;
  const argsText =
    args && typeof args === "object" ? JSON.stringify(args) : "";
  const parts = [
    event.correlation_id,
    event.tool?.qualified,
    event.tool?.command,
    argsText,
    event.tool?.input_hash,
    event.source?.adapter,
    event.agent?.skill_id,
    event.action?.type,
    event.action?.outcome,
    event.action?.reason,
    event.dlp && typeof event.dlp === "object" ? JSON.stringify(event.dlp) : "",
    event.tool_policy && typeof event.tool_policy === "object"
      ? JSON.stringify(event.tool_policy)
      : "",
  ];
  return parts.filter(Boolean).join(" ").toLowerCase();
}

/** TIME_WINDOWS index for "All" — matches weekly stats better than 15m/1h. */
const ALL_TIME_WINDOW_IDX = TIME_WINDOWS.length - 1;

export type ColumnId = "time" | "action" | "tool" | "mitre" | "command" | "source" | "actor" | "correlation_id" | "agent" | "initiator" | "model" | "skill" | "host_id" | "reason" | "mcp_server";

export interface ColumnDef {
  id: ColumnId;
  label: string;
  widthClass: string;
  render: (event: AuditEvent, formatTime: (t?: string) => string, type: string, outcome: string, Icon: any, sourceApp: string) => React.ReactNode;
}

const CELL_MUTED = "truncate font-mono text-[12px] text-subtle";
const CELL = "truncate font-mono text-[12px] text-muted-foreground";
const DASH = <span className="text-subtle">—</span>;

export const COLUMN_REGISTRY: Record<ColumnId, ColumnDef> = {
  time: {
    id: "time", label: "Time", widthClass: "w-24",
    render: (e, f) => <div className={CELL_MUTED}>{f(e.timestamp_utc)}</div>
  },
  action: {
    id: "action", label: "Action", widthClass: "w-32",
    render: (e, f, type, outcome) => (
      <div className={`flex items-center gap-2 truncate font-mono text-[12px] ${type === "detection" ? "font-medium text-danger" : "text-foreground"}`}>
        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${outcomeDot(outcome)}`} />
        <span className="truncate">{type}</span>
      </div>
    )
  },
  tool: {
    id: "tool", label: "Tool", widthClass: "w-32",
    render: (e) => <div className="truncate font-mono text-[12px] text-foreground" title={e.tool?.qualified || e.tool?.name || ""}>{e.tool?.qualified || e.tool?.name || DASH}</div>
  },
  mitre: {
    id: "mitre", label: "MITRE", widthClass: "w-24",
    render: (e) => {
      const m = e.tool?.mitre;
      if (!m) return <div className="text-[12px]">{DASH}</div>;
      const cred = m.tactic_id === "TA0006" || m.tactic_id === "TA0010"; // credential access / exfil = high signal
      return (
        <div className="truncate" title={`${m.tactic}: ${m.technique}${m.technique_id ? ` (${m.technique_id})` : ""}`}>
          <Technique id={m.technique_id || m.tactic?.split(" ")[0] || "—"} tone={cred ? "alert" : "default"} />
        </div>
      );
    }
  },
  command: {
    id: "command", label: "Command", widthClass: "min-w-[200px] flex-1",
    render: (e, f, type) =>
      type === "detection" ? (
        <div className="truncate text-[13px] font-medium text-foreground" title={e.detection?.title || e.action?.reason || ""}>
          {e.detection?.title || e.action?.reason || "—"}
        </div>
      ) : (
        <div className={CELL} title={e.tool?.command || ""}>{e.tool?.command || DASH}</div>
      )
  },
  source: {
    id: "source", label: "Source", widthClass: "w-24",
    render: (e, f, t, o, i, sourceApp) => <div className="truncate"><SourceBadge app={sourceApp} /></div>
  },
  actor: {
    id: "actor", label: "Actor", widthClass: "w-24",
    render: (e) => <div className={CELL_MUTED} title={e.actor?.id || ""}>{e.actor?.id || "—"}</div>
  },
  correlation_id: {
    id: "correlation_id", label: "Session ID", widthClass: "w-40",
    render: (e) => <div className={CELL_MUTED} title={e.correlation_id || ""}>{e.correlation_id || "—"}</div>
  },
  agent: {
    id: "agent", label: "Agent Name", widthClass: "w-32",
    render: (e) => <div className={CELL_MUTED}>{e.agent?.name || "—"}</div>
  },
  initiator: {
    id: "initiator", label: "Initiator", widthClass: "w-32",
    render: (e) => <div className={CELL_MUTED}>{e.initiator?.operator_id || "—"}</div>
  },
  model: {
    id: "model", label: "Model ID", widthClass: "w-40",
    render: (e) => <div className={CELL_MUTED}>{e.model?.id || "—"}</div>
  },
  skill: {
    id: "skill", label: "Skill", widthClass: "w-32",
    render: (e) => <div className={CELL_MUTED}>{e.agent?.skill_id || "—"}</div>
  },
  host_id: {
    id: "host_id", label: "Host", widthClass: "w-32",
    render: (e) => <div className={CELL_MUTED}>{e.host_id || "—"}</div>
  },
  reason: {
    id: "reason", label: "Reason / Error", widthClass: "w-44",
    render: (e, f, type) => (
      <div className={`truncate text-[12px] ${type === "detection" ? "text-muted-foreground" : "text-danger"}`} title={e.action?.reason || ""}>
        {e.action?.reason || DASH}
      </div>
    )
  },
  mcp_server: {
    id: "mcp_server", label: "MCP Server", widthClass: "w-32",
    render: (e) => <div className={CELL_MUTED}>{e.mcp?.server_id || "—"}</div>
  }
};

// The eight columns that carry the story. The rest (model, skill, host, mcp,
// session id, agent, initiator) are one click away in the Columns manager —
// twelve-by-default overflowed the viewport and collapsed the Command column.
export const DEFAULT_COLUMNS: ColumnId[] = ["time", "action", "tool", "mitre", "command", "source", "actor", "reason"];

const DETECTION_SEVERITIES = new Set<Detection["severity"]>(["critical", "high", "medium", "low"]);

function detectionSeverity(outcome?: string): Detection["severity"] {
  if (outcome && DETECTION_SEVERITIES.has(outcome as Detection["severity"])) {
    return outcome as Detection["severity"];
  }
  return "medium";
}

export function detectionsFromEvents(events: AuditEvent[]): Detection[] {
  const byKey = new Map<string, Detection>();
  for (const ev of events) {
    if (ev.action?.type !== "detection") continue;
    if (ev.detection?.rule_id) {
      const d = ev.detection;
      byKey.set(`${d.rule_id}:${d.correlation_id}`, d);
      continue;
    }
    const ruleId = ev.source_topic?.replace(/^detection\//, "") || ev.event_id || "detection";
    byKey.set(`${ruleId}:${ev.correlation_id ?? ""}`, {
      rule_id: ruleId,
      title: ruleId,
      severity: detectionSeverity(ev.action?.outcome),
      summary: ev.action?.reason || "",
      correlation_id: ev.correlation_id || "",
      tactic_ids: ev.tool?.mitre?.tactic_id ? [ev.tool.mitre.tactic_id] : [],
      technique_ids: ev.tool?.mitre?.technique_id ? [ev.tool.mitre.technique_id] : [],
      event_ids: ev.event_id ? [ev.event_id] : [],
      first_seen_utc: ev.timestamp_utc || "",
      last_seen_utc: ev.timestamp_utc || "",
    });
  }
  return Array.from(byKey.values());
}

function EventRow({
  event,
  highlight,
  selected,
  onSelect,
  columns,
}: {
  event: AuditEvent;
  highlight: boolean;
  selected: boolean;
  onSelect: (event: AuditEvent) => void;
  columns: ColumnId[];
}) {
  const type = event.action?.type ?? "event";
  const outcome = event.action?.outcome ?? "";
  const sourceApp = eventSourceApp(event);
  const Icon = ACTION_ICONS[type] ?? XCircle;

  return (
    <button
      type="button"
      aria-pressed={selected}
      className={`flex w-full items-center gap-3 border-b border-border px-4 py-2 text-left transition-colors last:border-b-0 ${
        selected ? "bg-muted shadow-[inset_2px_0_0_hsl(var(--signal))]" : `${rowOutcomeClass(outcome, highlight)} hover:bg-muted/60`
      }`}
      onClick={() => onSelect(event)}
    >
      {columns.map((colId) => {
        const c = COLUMN_REGISTRY[colId];
        if (!c) return null;
        return (
          <div key={colId} className={`shrink-0 ${c.widthClass}`}>
            {c.render(event, formatTime, type, outcome, Icon, sourceApp)}
          </div>
        );
      })}
    </button>
  );
}

function FilterChip({
  active,
  label,
  onClick,
  dot,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
  dot: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`inline-flex h-7 items-center gap-1.5 rounded-sm border px-2.5 text-[12px] font-medium transition-colors ${
        active
          ? "border-border bg-card text-foreground hover:border-foreground/25"
          : "border-dashed border-border text-subtle hover:text-muted-foreground"
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${active ? dot : "bg-subtle/40"}`} />
      {label}
    </button>
  );
}

export function FlightRecorderPanel() {
  const threadId = useAgentStore((s) => s.threadId);
  const sessionId = useAgentStore((s) => s.sessionId);
  const fleetScope = useAgentStore((s) => s.fleetScope);
  const setFleetScope = useAgentStore((s) => s.setFleetScope);
  const runsRefreshKey = useAgentStore((s) => s.runsRefreshKey);
  const pinnedDetection = useAgentStore((s) => s.pinnedDetection);
  const clearPinnedDetection = useAgentStore((s) => s.clearPinnedDetection);
  const feedFocus = useAgentStore((s) => s.feedFocus);
  const clearFeedFocus = useAgentStore((s) => s.clearFeedFocus);
  const huntFocus = useAgentStore((s) => s.huntFocus);
  const setHuntFocus = useAgentStore((s) => s.setHuntFocus);

  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [columns, setColumns] = useState<ColumnId[]>(DEFAULT_COLUMNS);
  const [showColumnManager, setShowColumnManager] = useState(false);
  const [draggedCol, setDraggedCol] = useState<ColumnId | null>(null);

  useEffect(() => {
    try {
      const saved = localStorage.getItem("agentmetry-columns-v2");
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed) && parsed.length > 0) {
          setColumns(parsed);
        }
      }
    } catch {}
  }, []);

  const updateColumns = (newCols: ColumnId[]) => {
    setColumns(newCols);
    localStorage.setItem("agentmetry-columns-v2", JSON.stringify(newCols));
  };

  const handleDragStart = (e: React.DragEvent, colId: ColumnId) => {
    setDraggedCol(colId);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault(); // Necessary to allow dropping
  };

  const handleDrop = (e: React.DragEvent, targetColId: ColumnId) => {
    e.preventDefault();
    if (!draggedCol || draggedCol === targetColId) return;
    const newCols = [...columns];
    const draggedIdx = newCols.indexOf(draggedCol);
    const targetIdx = newCols.indexOf(targetColId);
    newCols.splice(draggedIdx, 1);
    newCols.splice(targetIdx, 0, draggedCol);
    updateColumns(newCols);
    setDraggedCol(null);
  };

  const [loadingOlder, setLoadingOlder] = useState(false);
  const [loadingNewer, setLoadingNewer] = useState(false);
  const [sessionView, setSessionView] = useState<string | null>(null);
  const [sessionTruncated, setSessionTruncated] = useState(false);
  const [detections, setDetections] = useState<Detection[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [pagination, setPagination] = useState<AuditPagination>({
    has_older: false,
    has_newer: false,
  });
  const [atLatest, setAtLatest] = useState(true);
  const [sourceFilter, setSourceFilter] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearchQuery, setDebouncedSearchQuery] = useState("");
  const [eventTypeFilter, setEventTypeFilter] = useState<string>("all");

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearchQuery(searchQuery), 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  const [timeWindowIdx, setTimeWindowIdx] = useState(1);
  const [outcomeFilters, setOutcomeFilters] = useState({
    success: true,
    pending: true,
    issues: true,
  });
  const [selectedEventKey, setSelectedEventKey] = useState<string | null>(null);
  const [detectionRuleFilter, setDetectionRuleFilter] = useState<string | null>(null);

  const timeWindow = TIME_WINDOWS[timeWindowIdx] ?? TIME_WINDOWS[1];

  const buildParams = useCallback(
    (
      extra?: { before_utc?: string; after_utc?: string },
      focusOverride?: FeedFocusKind | null,
    ) => {
      // Hunt mode mirrors Analytics stats (fleet, 7 days, server focus).
      // Default SIEM view is fleet-wide; "This session" narrows to the browser id.
      const focusKind = focusOverride === undefined ? huntFocus : focusOverride;
      const hunting = focusKind != null;
      const params = new URLSearchParams({
        limit: String(hunting ? 500 : timeWindow.limit),
        scope: hunting || fleetScope ? "all" : "runs",
      });
      if (!hunting) params.set("sources", ALL_SOURCE_APPS.join(","));
      if (!hunting && !fleetScope && sessionId) params.set("session_id", sessionId);
      if (hunting) {
        params.set("since_minutes", String(FEED_FOCUS_SINCE_MINUTES));
        const focus = tailFocusParam(focusKind);
        if (focus) params.set("focus", focus);
      } else if (timeWindow.minutes != null) {
        params.set("since_minutes", String(timeWindow.minutes));
      }
      if (extra?.before_utc) params.set("before_utc", extra.before_utc);
      if (extra?.after_utc) params.set("after_utc", extra.after_utc);
      return params;
    },
    [huntFocus, fleetScope, sessionId, timeWindow],
  );

  const fetchPage = useCallback(
    async (
      mode: "latest" | "older" | "newer",
      cursor?: string,
      focusOverride?: FeedFocusKind | null,
    ) => {
      const params =
        mode === "older" && cursor
          ? buildParams({ before_utc: cursor }, focusOverride)
          : mode === "newer" && cursor
            ? buildParams({ after_utc: cursor }, focusOverride)
            : buildParams(undefined, focusOverride);

      const res = await fetch(`${ORCHESTRATOR_URL}/api/v1/audit/tail?${params}`, {
        headers: apiHeaders(),
        credentials: "include",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const page = (data.events ?? []) as AuditEvent[];
      const pageInfo = (data.pagination ?? {}) as AuditPagination;

      if (mode === "older") {
        setEvents((prev) => mergeEvents(prev, page, "prepend"));
        setPagination((prev) => ({ ...prev, has_older: pageInfo.has_older ?? false, has_newer: true }));
        setAtLatest(false);
      } else if (mode === "newer") {
        setEvents((prev) => mergeEvents(prev, page, "append"));
        const stillHasNewer = pageInfo.has_newer ?? false;
        setPagination((prev) => ({ ...prev, has_newer: stillHasNewer, has_older: true }));
        if (!stillHasNewer) setAtLatest(true);
      } else {
        setEvents(page);
        setPagination(pageInfo);
        setAtLatest(!(pageInfo.has_newer ?? false));
      }
      setError(null);
      return page;
    },
    [buildParams],
  );

  const fetchTail = useCallback(async () => {
    try {
      await fetchPage("latest");
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, [fetchPage]);

  const loadOlder = useCallback(async () => {
    const oldest = events[0]?.timestamp_utc;
    if (!oldest || loadingOlder) return;
    setLoadingOlder(true);
    try {
      await fetchPage("older", oldest);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoadingOlder(false);
    }
  }, [events, fetchPage, loadingOlder]);

  const loadNewer = useCallback(async () => {
    const newest = events[events.length - 1]?.timestamp_utc;
    if (!newest || loadingNewer) return;
    setLoadingNewer(true);
    try {
      await fetchPage("newer", newest);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoadingNewer(false);
    }
  }, [events, fetchPage, loadingNewer]);

  const jumpToLatest = useCallback(async () => {
    setLoading(true);
    try {
      await fetchPage("latest");
      setAtLatest(true);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, [fetchPage]);

  // Server-side full-session lookup — scans the whole trail, not just the
  // loaded window, so viewing an older session actually works.
  const openSession = useCallback(async (corrId: string) => {
    setLoading(true);
    setSessionView(corrId);
    setAtLatest(false);
    try {
      const [sessionRes, detRes] = await Promise.all([
        fetch(`${ORCHESTRATOR_URL}/api/v1/audit/session/${encodeURIComponent(corrId)}`, {
          headers: apiHeaders(),
          credentials: "include",
        }),
        fetch(`${ORCHESTRATOR_URL}/api/v1/audit/detections/${encodeURIComponent(corrId)}`, {
          headers: apiHeaders(),
          credentials: "include",
        }),
      ]);
      if (!sessionRes.ok) throw new Error(`HTTP ${sessionRes.status}`);
      const data = await sessionRes.json();
      const sessionEvents = (data.events ?? []) as AuditEvent[];
      setEvents(sessionEvents);
      // The endpoint caps at 2000 events; a session at the cap is almost
      // certainly longer than what loaded, and hiding that would misrepresent
      // the trail.
      setSessionTruncated(sessionEvents.length >= 2000);
      setPagination({ has_older: false, has_newer: false });
      // Detections are best-effort: a failed correlation shouldn't hide the trail.
      setDetections(detRes.ok ? (((await detRes.json()).detections ?? []) as Detection[]) : []);
      setError(null);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  const exitSession = useCallback(async () => {
    setSessionView(null);
    setSessionTruncated(false);
    setDetections([]);
    await jumpToLatest();
  }, [jumpToLatest]);

  useEffect(() => {
    if (sessionView) return; // don't clobber a pinned session view
    setLoading(true);
    void fetchTail();
  }, [fetchTail, runsRefreshKey, timeWindowIdx, fleetScope, sessionId, sessionView]);

  useEffect(() => {
    if (!atLatest || sessionView) return;
    const timer = window.setInterval(() => void fetchPage("latest"), 8000);
    return () => window.clearInterval(timer);
  }, [atLatest, fetchPage, sessionView]);

  // A detection opened from the Detections section: pin its session, filter the
  // feed to the rule, then clear the request so it fires once.
  useEffect(() => {
    if (!pinnedDetection) return;
    const { correlationId, ruleId } = pinnedDetection;
    void openSession(correlationId).then(() => setDetectionRuleFilter(ruleId));
    clearPinnedDetection();
  }, [pinnedDetection, openSession, clearPinnedDetection]);

  // Analytics dogfood stats → filter the feed to the events behind a count.
  useEffect(() => {
    if (!feedFocus || feedFocus.kind === "detections") return;
    const kind = feedFocus.kind;
    setSessionView(null);
    setSessionTruncated(false);
    setDetectionRuleFilter(null);
    setSearchQuery("");
    setDebouncedSearchQuery("");
    setSourceFilter("all");
    setEventTypeFilter("all");
    setTimeWindowIdx(ALL_TIME_WINDOW_IDX);
    setOutcomeFilters(outcomeFiltersForFocus(kind));
    setHuntFocus(kind);
    clearFeedFocus();
  }, [feedFocus, clearFeedFocus, setHuntFocus]);

  // Re-fetch once hunt focus is applied so buildParams includes the server filter.
  useEffect(() => {
    if (!huntFocus || sessionView) return;
    setLoading(true);
    void fetchTail();
  }, [huntFocus]); // eslint-disable-line react-hooks/exhaustive-deps -- intentional: only on focus change

  const clearActiveFocus = useCallback(() => {
    setHuntFocus(null);
    setOutcomeFilters({ success: true, pending: true, issues: true });
    setLoading(true);
    void fetchPage("latest", undefined, null).finally(() => setLoading(false));
  }, [fetchPage, setHuntFocus]);

  const filteredEvents = useMemo(() => {
    const q = debouncedSearchQuery.trim().toLowerCase();
    return events.filter((ev) => {
      if (sourceFilter !== "all" && eventSourceApp(ev) !== sourceFilter) return false;
      const type = ev.action?.type ?? "";
      if (eventTypeFilter !== "all" && type !== eventTypeFilter) return false;
      const outcome = ev.action?.outcome ?? "";
      // A detection's outcome IS its severity (critical/high/medium), not a
      // standard outcome — group it with issues so it isn't silently filtered out.
      const isDetection = type === "detection";
      const isIssue = outcome === "denied" || outcome === "error" || isDetection;
      const outcomeOk =
        (outcome === "success" && outcomeFilters.success) ||
        (outcome === "pending" && outcomeFilters.pending) ||
        (isIssue && outcomeFilters.issues) ||
        (!outcome && outcomeFilters.success);
      if (!outcomeOk) return false;
      if (huntFocus && !eventMatchesFocus(ev, huntFocus)) return false;
      if (q && !eventSearchHaystack(ev).includes(q)) return false;
      return true;
    });
  }, [
    events,
    sourceFilter,
    eventTypeFilter,
    outcomeFilters,
    debouncedSearchQuery,
    huntFocus,
  ]);

  const visibleDetections = useMemo(() => {
    const merged = new Map<string, Detection>();
    for (const d of [...detections, ...detectionsFromEvents(events)]) {
      merged.set(`${d.rule_id}:${d.correlation_id}`, d);
    }
    return Array.from(merged.values());
  }, [events, detections]);

  const displayEvents = useMemo(() => {
    if (!detectionRuleFilter) return filteredEvents;
    const det = visibleDetections.find((d) => d.rule_id === detectionRuleFilter);
    if (!det) return filteredEvents;
    const ids = new Set(det.event_ids);
    return filteredEvents.filter(
      (ev) =>
        (ev.event_id && ids.has(ev.event_id)) ||
        (ev.action?.type === "detection" && ev.detection?.rule_id === detectionRuleFilter),
    );
  }, [filteredEvents, detectionRuleFilter, visibleDetections]);

  const selectedEvent = useMemo(
    () => displayEvents.find((ev) => eventKey(ev) === selectedEventKey) ?? null,
    [displayEvents, selectedEventKey],
  );

  const toggleOutcome = (key: keyof typeof outcomeFilters) => {
    setOutcomeFilters((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      {huntFocus ? (
        <div className="flex items-center justify-between gap-3 rounded-sm border border-caution/40 bg-caution/10 px-3 py-2 text-[13px]">
          <span className="min-w-0 truncate">
            <span className="font-medium text-caution">Focus: {FEED_FOCUS_LABELS[huntFocus]}</span>
            <span className="ml-2 text-muted-foreground">
              Last 7 days, fleet-wide, up to 500 rows. Click a row for the reason and tool.
            </span>
          </span>
          <button type="button" onClick={clearActiveFocus} className="btn h-7 shrink-0">
            Clear
          </button>
        </div>
      ) : null}
      {sessionView ? (
        <div className="flex items-center justify-between gap-3 rounded-sm border border-signal/40 bg-signal/[0.08] px-3 py-2 text-[13px]">
          <span className="min-w-0 truncate">
            <span className="text-muted-foreground">Pinned session</span>{" "}
            <span className="font-mono font-medium text-foreground">{sessionView}</span>
            {sessionTruncated ? (
              <span className="ml-2 text-muted-foreground">First 2000 events</span>
            ) : null}
          </span>
          <button type="button" onClick={() => void exitSession()} className="btn h-7 shrink-0">
            Back to live
          </button>
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <label className="relative min-w-[16rem] flex-1">
          <span className="sr-only">Search events</span>
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-subtle" />
          <input
            type="search"
            placeholder="Search tool, command, session or hash"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="control w-full pl-8 placeholder:text-subtle"
          />
        </label>
        <select
          aria-label="Source"
          className="control"
          value={sourceFilter}
          onChange={(e) => setSourceFilter(e.target.value)}
        >
          <option value="all">All sources</option>
          {ALL_SOURCE_APPS.map((s) => (
            <option key={s} value={s}>
              {sourceLabel(s)}
            </option>
          ))}
        </select>
        <select
          aria-label="Event type"
          className="control"
          value={eventTypeFilter}
          onChange={(e) => setEventTypeFilter(e.target.value)}
        >
          <option value="all">All types</option>
          {EVENT_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <Segmented
          label="Scope"
          items={[
            { value: "fleet", label: "Fleet" },
            { value: "session", label: "This session" },
          ]}
          value={fleetScope ? "fleet" : "session"}
          onChange={(v) => setFleetScope(v === "fleet")}
        />
        <Segmented
          label="Time window"
          items={TIME_WINDOWS.map((w, i) => ({ value: String(i), label: w.label }))}
          value={huntFocus ? null : String(timeWindowIdx)}
          disabled={!!huntFocus}
          onChange={(v) => setTimeWindowIdx(Number(v))}
        />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[12px] text-subtle">Outcome</span>
        <FilterChip active={outcomeFilters.success} label="OK" dot="bg-secure" onClick={() => toggleOutcome("success")} />
        <FilterChip active={outcomeFilters.pending} label="Pending" dot="bg-caution" onClick={() => toggleOutcome("pending")} />
        <FilterChip active={outcomeFilters.issues} label="Issues" dot="bg-danger" onClick={() => toggleOutcome("issues")} />
        <span className="ml-1 text-[12px] text-muted-foreground">
          <span className="font-mono text-foreground">{displayEvents.length}</span> shown
          {huntFocus ? ", hunt" : fleetScope ? ", fleet" : ", this session"}
          {sessionView ? ", pinned session" : !atLatest ? ", history" : ""}
        </span>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <button type="button" className="btn" onClick={() => downloadAuditJsonl(displayEvents)}>
            JSONL
          </button>
          <button type="button" className="btn" onClick={() => downloadAuditCsv(displayEvents)}>
            CSV
          </button>
          <div className="relative">
            <button
              type="button"
              aria-expanded={showColumnManager}
              onClick={() => setShowColumnManager(!showColumnManager)}
              className="btn"
            >
              <Settings2 className="h-3.5 w-3.5" />
              Columns
            </button>
            {showColumnManager && (
              <div className="absolute right-0 top-full z-50 mt-1.5 w-64 rounded-sm border border-border bg-popover p-1.5 shadow-xl shadow-black/30">
                <div className="eyebrow px-2 pb-1.5 pt-1">Columns</div>
                <div className="flex max-h-72 flex-col overflow-y-auto">
                  {[...columns, ...(Object.keys(COLUMN_REGISTRY) as ColumnId[]).filter((k) => !columns.includes(k))].map(
                    (colId) => {
                      const c = COLUMN_REGISTRY[colId];
                      const isActive = columns.includes(colId);
                      const idx = columns.indexOf(colId);
                      return (
                        <div key={colId} className="flex items-center justify-between rounded-sm px-2 py-1.5 hover:bg-muted">
                          <button
                            type="button"
                            onClick={() => {
                              if (isActive) updateColumns(columns.filter((x) => x !== colId));
                              else updateColumns([...columns, colId]);
                            }}
                            className="flex items-center gap-2 text-[13px]"
                            aria-pressed={isActive}
                          >
                            <span
                              className={`flex h-4 w-4 items-center justify-center rounded-sm border ${
                                isActive ? "border-signal bg-signal/15 text-signal" : "border-border text-subtle"
                              }`}
                            >
                              {isActive ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />}
                            </span>
                            <span className={isActive ? "text-foreground" : "text-muted-foreground"}>{c.label}</span>
                          </button>
                          {isActive && (
                            <div className="flex gap-1 text-muted-foreground">
                              <button type="button" aria-label={`Move ${c.label} up`} disabled={idx === 0} onClick={() => { const n = [...columns]; [n[idx - 1], n[idx]] = [n[idx], n[idx - 1]]; updateColumns(n); }} className="hover:text-foreground disabled:opacity-30"><ArrowUp className="h-3 w-3" /></button>
                              <button type="button" aria-label={`Move ${c.label} down`} disabled={idx === columns.length - 1} onClick={() => { const n = [...columns]; [n[idx + 1], n[idx]] = [n[idx], n[idx + 1]]; updateColumns(n); }} className="hover:text-foreground disabled:opacity-30"><ArrowDown className="h-3 w-3" /></button>
                            </div>
                          )}
                        </div>
                      );
                    },
                  )}
                </div>
              </div>
            )}
          </div>
          <button type="button" className="btn" onClick={() => void fetchTail()}>
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </button>
        </div>
      </div>

      <DetectionsStrip
        detections={visibleDetections}
        activeRuleId={detectionRuleFilter}
        onSelect={setDetectionRuleFilter}
        onOpenSession={(corrId) => void openSession(corrId)}
      />
      <EventHistogram events={displayEvents} />

      <div className="flex min-h-0 flex-1 flex-col gap-3 lg:flex-row">
        <div className="panel flex min-h-[16rem] min-w-0 flex-1 flex-col overflow-hidden">
          <div className="min-h-0 flex-1 overflow-auto">
            {loading && displayEvents.length === 0 ? (
              <EmptyState>Loading audit events…</EmptyState>
            ) : error && displayEvents.length === 0 ? (
              <EmptyState>
                <span className="text-danger">{error}</span>
              </EmptyState>
            ) : displayEvents.length === 0 ? (
              <EmptyState>
                {huntFocus
                  ? `No ${FEED_FOCUS_LABELS[huntFocus].toLowerCase()} in the last 7 days. Clear focus or check ingest.`
                  : fleetScope
                    ? "No events match these filters. Try a wider time window, or open Analytics for weekly counts."
                    : "No events for this dashboard session. Switch to Fleet to see all hosts."}
              </EmptyState>
            ) : (
              <div className="min-w-[1080px]">
                <div className="sticky top-0 z-10 flex items-center gap-3 border-b border-border bg-card px-4 py-2">
                  {columns.map((colId) => {
                    const c = COLUMN_REGISTRY[colId];
                    if (!c) return null;
                    return (
                      <div
                        key={colId}
                        className={`eyebrow shrink-0 cursor-grab select-none hover:text-foreground ${c.widthClass} ${draggedCol === colId ? "opacity-50" : ""}`}
                        draggable
                        onDragStart={(e) => handleDragStart(e, colId)}
                        onDragOver={handleDragOver}
                        onDrop={(e) => handleDrop(e, colId)}
                        onDragEnd={() => setDraggedCol(null)}
                      >
                        {c.label}
                      </div>
                    );
                  })}
                </div>
                {displayEvents.map((ev, i) => (
                  <EventRow
                    key={eventKey(ev) || `${i}`}
                    columns={columns}
                    event={ev}
                    highlight={!!threadId && ev.correlation_id === threadId}
                    selected={selectedEventKey === eventKey(ev)}
                    onSelect={(e) => setSelectedEventKey(eventKey(e))}
                  />
                ))}
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-3 py-2">
            <div className="flex items-center gap-1.5">
              <button type="button" disabled={!pagination.has_older || loadingOlder} onClick={() => void loadOlder()} className="btn h-7">
                <ChevronLeft className="h-3.5 w-3.5" /> Older
              </button>
              <button type="button" disabled={!pagination.has_newer || loadingNewer} onClick={() => void loadNewer()} className="btn h-7">
                Newer <ChevronRight className="h-3.5 w-3.5" />
              </button>
              {!atLatest ? (
                <button type="button" onClick={() => void jumpToLatest()} className="btn h-7 border-signal/40 text-signal">
                  Latest
                </button>
              ) : null}
            </div>
            {selectedEvent ? (
              <button type="button" className="text-[12px] text-muted-foreground hover:text-foreground lg:hidden" onClick={() => setSelectedEventKey(null)}>
                Close inspector
              </button>
            ) : (
              <span className="text-[12px] text-subtle">
                {atLatest && !sessionView ? "Live, refreshes every 8 s" : "Paused on history"}
              </span>
            )}
          </div>
        </div>

        {selectedEvent ? (
          <div className="panel flex max-h-[28rem] w-full shrink-0 flex-col overflow-hidden lg:max-h-none lg:w-80 xl:w-96">
            <EventInspector
              event={selectedEvent}
              onClose={() => setSelectedEventKey(null)}
              onViewSession={(corrId) => void openSession(corrId)}
              onSelectEventId={(id) => {
                const match = displayEvents.find((ev) => ev.event_id === id);
                if (match) setSelectedEventKey(eventKey(match));
              }}
              hasEventId={(id) => displayEvents.some((ev) => ev.event_id === id)}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}
