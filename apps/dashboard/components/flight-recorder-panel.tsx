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
  Settings2, ArrowUp, ArrowDown, Eye, EyeOff
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useAgentStore } from "@/lib/store";
import { ORCHESTRATOR_URL } from "@/lib/utils";
import { apiHeaders } from "@/lib/api";
import { eventSourceApp, sourceBadgeClass, sourceLabel } from "@/lib/audit-source";
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

const ALL_SOURCES = ["agentmetry", "cursor", "claude", "codex", "antigravity", "mcp_proxy"] as const;

const EVENT_TYPES = [
  "session_start",
  "session_end",
  "tool_called",
  "approval_request",
  "approval_response",
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
    <span
      className={`shrink-0 rounded px-1.5 py-0.5 text-xs uppercase tracking-wide ${sourceBadgeClass(app)}`}
    >
      {sourceLabel(app)}
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
      return "bg-emerald-400";
    case "critical":  // detection severity
      return "bg-red-500 animate-pulse";
    case "high":
    case "medium":    // detection severity
      return "bg-amber-400";
    case "denied":
    case "error":
      return "bg-red-400";
    case "pending":
      return "bg-amber-400 animate-pulse";
    default:
      return "bg-slate-500";
  }
}

function rowOutcomeClass(outcome?: string, highlight?: boolean): string {
  if (highlight) return "border-emerald-500/40 bg-emerald-50/80 dark:bg-emerald-950/25";
  switch (outcome) {
    case "critical":
      return "border-red-500/70 bg-red-50 dark:bg-red-950/40";
    case "high":
    case "medium":
      return "border-amber-500/60 bg-amber-50 dark:bg-amber-950/25";
    case "denied":
    case "error":
      return "border-red-400/50 bg-red-50 dark:bg-red-950/20";
    case "pending":
      return "border-amber-400/40 bg-amber-50 dark:bg-amber-950/15";
    default:
      return "border-border bg-card/60 dark:bg-slate-950/40";
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
  ];
  return parts.filter(Boolean).join(" ").toLowerCase();
}

export type ColumnId = "time" | "action" | "tool" | "mitre" | "command" | "source" | "actor" | "correlation_id" | "agent" | "initiator" | "model" | "skill" | "host_id" | "reason" | "mcp_server";

export interface ColumnDef {
  id: ColumnId;
  label: string;
  widthClass: string;
  render: (event: AuditEvent, formatTime: (t?: string) => string, type: string, outcome: string, Icon: any, sourceApp: string) => React.ReactNode;
}

export const COLUMN_REGISTRY: Record<ColumnId, ColumnDef> = {
  time: {
    id: "time", label: "Time", widthClass: "w-32",
    render: (e, f) => <div className="truncate text-slate-500 dark:text-slate-400">{f(e.timestamp_utc)}</div>
  },
  action: {
    id: "action", label: "Action", widthClass: "w-40",
    render: (e, f, type, outcome, Icon) => (
      <div className="flex items-center gap-1.5 truncate text-emerald-700 dark:text-emerald-300">
        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${outcomeDot(outcome)}`} />
        <Icon className="h-3 w-3 shrink-0 text-emerald-400/80" />
        <span className="truncate">{type}</span>
      </div>
    )
  },
  tool: {
    id: "tool", label: "Tool", widthClass: "w-40",
    render: (e) => <div className="truncate text-slate-700 dark:text-slate-300" title={e.tool?.qualified || e.tool?.name || ""}>{e.tool?.qualified || e.tool?.name || "—"}</div>
  },
  mitre: {
    id: "mitre", label: "Mitre", widthClass: "w-40",
    render: (e) => {
      const m = e.tool?.mitre;
      if (!m) return <div className="text-muted-foreground text-base">—</div>;
      const cred = m.tactic_id === "TA0006" || m.tactic_id === "TA0010"; // credential access / exfil = high signal
      return (
        <div className="truncate text-base" title={`${m.tactic} — ${m.technique}${m.technique_id ? ` (${m.technique_id})` : ""}`}>
          <span className={`inline-flex items-center rounded-md px-2 py-1 text-sm font-mono font-medium ring-1 ring-inset ${
            cred
              ? "bg-red-50 text-red-700 ring-red-600/20 dark:bg-red-400/10 dark:text-red-400 dark:ring-red-400/20"
              : "bg-emerald-50 text-emerald-700 ring-emerald-600/20 dark:bg-emerald-400/10 dark:text-emerald-400 dark:ring-emerald-400/20"
          }`}>
            {m.technique_id || m.tactic?.split(" ")[0] || "—"}
          </span>
        </div>
      );
    }
  },
  command: {
    id: "command", label: "Command", widthClass: "min-w-[200px] flex-1",
    render: (e) => <div className="truncate text-muted-foreground font-mono text-base" title={e.tool?.command || ""}>{e.tool?.command || "—"}</div>
  },
  source: {
    id: "source", label: "Source", widthClass: "w-28",
    render: (e, f, t, o, i, sourceApp) => <div className="truncate"><SourceBadge app={sourceApp} /></div>
  },
  actor: {
    id: "actor", label: "Actor", widthClass: "w-32",
    render: (e) => <div className="truncate text-slate-500 dark:text-slate-400 text-sm" title={e.actor?.id || ""}>{e.actor?.id || "—"}</div>
  },
  correlation_id: {
    id: "correlation_id", label: "Session ID", widthClass: "w-40",
    render: (e) => <div className="truncate text-slate-500 dark:text-slate-400 text-sm" title={e.correlation_id || ""}>{e.correlation_id || "—"}</div>
  },
  agent: {
    id: "agent", label: "Agent Name", widthClass: "w-32",
    render: (e) => <div className="truncate text-slate-500 dark:text-slate-400 text-sm">{e.agent?.name || "—"}</div>
  },
  initiator: {
    id: "initiator", label: "Initiator", widthClass: "w-32",
    render: (e) => <div className="truncate text-slate-500 dark:text-slate-400 text-sm">{e.initiator?.operator_id || "—"}</div>
  },
  model: {
    id: "model", label: "Model ID", widthClass: "w-40",
    render: (e) => <div className="truncate text-slate-500 dark:text-slate-400 text-sm">{e.model?.id || "—"}</div>
  },
  skill: {
    id: "skill", label: "Skill", widthClass: "w-32",
    render: (e) => <div className="truncate text-slate-500 dark:text-slate-400 text-sm">{e.agent?.skill_id || "—"}</div>
  },
  host_id: {
    id: "host_id", label: "Host", widthClass: "w-32",
    render: (e) => <div className="truncate text-slate-500 dark:text-slate-400 text-sm">{e.host_id || "—"}</div>
  },
  reason: {
    id: "reason", label: "Reason / Error", widthClass: "w-64",
    render: (e) => <div className="truncate text-red-500 dark:text-red-400 text-sm" title={e.action?.reason || ""}>{e.action?.reason || "—"}</div>
  },
  mcp_server: {
    id: "mcp_server", label: "MCP Server", widthClass: "w-32",
    render: (e) => <div className="truncate text-slate-500 dark:text-slate-400 text-sm">{e.mcp?.server_id || "—"}</div>
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
      className={`flex w-full items-center gap-4 border px-4 py-2.5 text-left font-mono text-base transition ${rowOutcomeClass(outcome, highlight)} ${
        selected ? "ring-1 ring-emerald-500/60 bg-emerald-50/80 dark:bg-emerald-950/20" : "hover:bg-muted/30"
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
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded px-2.5 py-1 text-base transition ${
        active
          ? "bg-emerald-100 text-emerald-900 ring-1 ring-emerald-600/30 dark:bg-emerald-900/50 dark:text-emerald-200 dark:ring-emerald-500/30"
          : "bg-slate-100 text-slate-500 hover:text-slate-700 dark:bg-slate-900 dark:text-slate-400 dark:hover:text-slate-300"
      }`}
    >
      {label}
    </button>
  );
}

export function FlightRecorderPanel() {
  const threadId = useAgentStore((s) => s.threadId);
  const sessionId = useAgentStore((s) => s.sessionId);
  const devMode = useAgentStore((s) => s.devMode);
  const runsRefreshKey = useAgentStore((s) => s.runsRefreshKey);

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
    (extra?: { before_utc?: string; after_utc?: string }) => {
      const params = new URLSearchParams({
        limit: String(timeWindow.limit),
        scope: devMode ? "all" : "runs",
        sources: ALL_SOURCES.join(","),
      });
      if (!devMode && sessionId) params.set("session_id", sessionId);
      if (timeWindow.minutes != null) params.set("since_minutes", String(timeWindow.minutes));
      if (extra?.before_utc) params.set("before_utc", extra.before_utc);
      if (extra?.after_utc) params.set("after_utc", extra.after_utc);
      return params;
    },
    [devMode, sessionId, timeWindow],
  );

  const fetchPage = useCallback(
    async (mode: "latest" | "older" | "newer", cursor?: string) => {
      const params =
        mode === "older" && cursor
          ? buildParams({ before_utc: cursor })
          : mode === "newer" && cursor
            ? buildParams({ after_utc: cursor })
            : buildParams();

      const res = await fetch(`${ORCHESTRATOR_URL}/api/v1/audit/tail?${params}`, {
        headers: apiHeaders(),
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
        }),
        fetch(`${ORCHESTRATOR_URL}/api/v1/audit/detections/${encodeURIComponent(corrId)}`, {
          headers: apiHeaders(),
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
  }, [fetchTail, runsRefreshKey, timeWindowIdx, devMode, sessionId, sessionView]);

  useEffect(() => {
    if (!atLatest || sessionView) return;
    const timer = window.setInterval(() => void fetchPage("latest"), 8000);
    return () => window.clearInterval(timer);
  }, [atLatest, fetchPage, sessionView]);

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
      if (q && !eventSearchHaystack(ev).includes(q)) return false;
      return true;
    });
  }, [events, sourceFilter, eventTypeFilter, outcomeFilters, debouncedSearchQuery]);

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
    <div className="flex min-h-0 flex-1 flex-col rounded-lg border border-border bg-card/20">
      <div className="space-y-3 border-b border-border/60 px-3 py-3">
        {sessionView ? (
          <div className="flex items-center justify-between gap-2 rounded border border-sky-300 bg-sky-50 px-3 py-2 text-sm text-sky-900 dark:border-sky-500/30 dark:bg-sky-950/30 dark:text-sky-200">
            <span className="truncate font-mono">
              Session <span className="text-sky-700 dark:text-sky-300">{sessionView}</span>
              {sessionTruncated ? (
                <span className="ml-2 text-sky-700/80 dark:text-sky-300/80">· first 2000 events</span>
              ) : null}
            </span>
            <button
              type="button"
              onClick={() => void exitSession()}
              className="shrink-0 rounded border border-sky-400/40 px-2 py-0.5 transition hover:bg-sky-100 dark:hover:bg-sky-900/40"
            >
              Back to live
            </button>
          </div>
        ) : null}

        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[12rem] flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input
              type="search"
              placeholder="Search tool, command, session, hash…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full rounded-md border border-border bg-background py-2 pl-9 pr-2 text-base text-foreground placeholder:text-muted-foreground focus:border-emerald-500/40 focus:outline-none"
            />
          </div>
          <select
            className="rounded-md border border-border bg-background px-2.5 py-2 text-sm text-muted-foreground"
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value)}
          >
            <option value="all">All sources</option>
            {ALL_SOURCES.map((s) => (
              <option key={s} value={s}>
                {sourceLabel(s)}
              </option>
            ))}
          </select>
          <select
            className="rounded-md border border-border bg-background px-2.5 py-2 text-sm text-muted-foreground"
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
          {TIME_WINDOWS.map((w, i) => (
            <FilterChip
              key={w.label}
              active={timeWindowIdx === i}
              label={w.label}
              onClick={() => setTimeWindowIdx(i)}
            />
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs uppercase tracking-wide text-muted-foreground">Outcome</span>
          <FilterChip active={outcomeFilters.success} label="OK" onClick={() => toggleOutcome("success")} />
          <FilterChip active={outcomeFilters.pending} label="Pending" onClick={() => toggleOutcome("pending")} />
          <FilterChip active={outcomeFilters.issues} label="Issues" onClick={() => toggleOutcome("issues")} />
          <span className="ml-2 font-mono text-xs text-muted-foreground">
            {displayEvents.length} shown
            {sessionView ? " · session" : !atLatest ? " · history" : ""}
          </span>
        </div>

        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border/50 pt-3">
          <button
            type="button"
            className="rounded-md border border-border px-2.5 py-1.5 text-xs uppercase tracking-wider text-muted-foreground transition hover:bg-muted hover:text-foreground"
            onClick={() => downloadAuditJsonl(displayEvents)}
          >
            JSONL
          </button>
          <button
            type="button"
            className="rounded-md border border-border px-2.5 py-1.5 text-xs uppercase tracking-wider text-muted-foreground transition hover:bg-muted hover:text-foreground"
            onClick={() => downloadAuditCsv(displayEvents)}
          >
            CSV
          </button>
          <div className="relative">
            <button
              onClick={() => setShowColumnManager(!showColumnManager)}
              className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs uppercase tracking-wider text-muted-foreground hover:bg-muted"
            >
              <Settings2 className="h-3.5 w-3.5" />
              Columns
            </button>
            {showColumnManager && (
              <div className="absolute right-0 top-full z-50 mt-2 w-64 rounded-md border border-border bg-card p-2 shadow-xl">
                <div className="mb-2 px-2 text-sm font-semibold text-muted-foreground">Manage columns</div>
                <div className="flex max-h-64 flex-col gap-1 overflow-y-auto">
                  {[...columns, ...(Object.keys(COLUMN_REGISTRY) as ColumnId[]).filter((k) => !columns.includes(k))].map(
                    (colId) => {
                      const c = COLUMN_REGISTRY[colId];
                      const isActive = columns.includes(colId);
                      const idx = columns.indexOf(colId);
                      return (
                        <div key={colId} className="flex items-center justify-between rounded px-2 py-1.5 hover:bg-muted/50">
                          <div className="flex items-center gap-2">
                            <button
                              onClick={() => {
                                if (isActive) updateColumns(columns.filter((x) => x !== colId));
                                else updateColumns([...columns, colId]);
                              }}
                              className={`flex h-4 w-4 items-center justify-center rounded border ${isActive ? "border-emerald-500 bg-emerald-500/20 text-emerald-400" : "border-border text-transparent"}`}
                            >
                              {isActive ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3 text-muted-foreground" />}
                            </button>
                            <span className="text-sm">{c.label}</span>
                          </div>
                          {isActive && (
                            <div className="flex gap-1">
                              <button disabled={idx === 0} onClick={() => { const n = [...columns]; [n[idx - 1], n[idx]] = [n[idx], n[idx - 1]]; updateColumns(n); }} className="disabled:opacity-30"><ArrowUp className="h-3 w-3" /></button>
                              <button disabled={idx === columns.length - 1} onClick={() => { const n = [...columns]; [n[idx + 1], n[idx]] = [n[idx], n[idx + 1]]; updateColumns(n); }} className="disabled:opacity-30"><ArrowDown className="h-3 w-3" /></button>
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
          <button
            type="button"
            className="rounded-md border border-border px-2.5 py-1.5 text-xs uppercase tracking-wider text-muted-foreground transition hover:bg-muted hover:text-foreground"
            onClick={() => void fetchTail()}
          >
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

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {loading && displayEvents.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground">Loading audit events…</p>
            ) : error && displayEvents.length === 0 ? (
              <p className="py-8 text-center text-sm text-red-400">{error}</p>
            ) : displayEvents.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground">
                No events match filters. Widen the time window or enable a Tier B source.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <div className="min-w-[1100px]">
                  <div className="mb-1 flex items-center gap-4 px-4 py-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    {columns.map((colId) => {
                      const c = COLUMN_REGISTRY[colId];
                      if (!c) return null;
                      return (
                        <div
                          key={colId}
                          className={`shrink-0 cursor-grab select-none hover:text-emerald-400 ${c.widthClass} ${draggedCol === colId ? "opacity-50" : ""}`}
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
                  <div className="space-y-1">
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
                </div>
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/60 px-3 py-2">
            <div className="flex items-center gap-1.5">
              <button type="button" disabled={!pagination.has_older || loadingOlder} onClick={() => void loadOlder()} className="inline-flex items-center gap-1 rounded border border-border px-2.5 py-1.5 text-sm text-muted-foreground disabled:opacity-40">
                <ChevronLeft className="h-3.5 w-3.5" /> Older
              </button>
              <button type="button" disabled={!pagination.has_newer || loadingNewer} onClick={() => void loadNewer()} className="inline-flex items-center gap-1 rounded border border-border px-2.5 py-1.5 text-sm text-muted-foreground disabled:opacity-40">
                Newer <ChevronRight className="h-3.5 w-3.5" />
              </button>
              {!atLatest ? (
                <button type="button" onClick={() => void jumpToLatest()} className="rounded border border-emerald-500/30 px-2.5 py-1.5 text-sm text-emerald-600 dark:text-emerald-300">
                  Latest
                </button>
              ) : null}
            </div>
            {selectedEvent ? (
              <button type="button" className="text-sm text-muted-foreground lg:hidden" onClick={() => setSelectedEventKey(null)}>
                Close inspector
              </button>
            ) : null}
          </div>
        </div>

        {selectedEvent ? (
          <div className="flex w-full shrink-0 flex-col border-t border-border/60 lg:w-80 lg:border-l lg:border-t-0 xl:w-96">
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
