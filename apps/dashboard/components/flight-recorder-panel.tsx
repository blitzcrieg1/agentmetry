"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Copy,
  Download,
  Play,
  Radio,
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
import { AuditJsonView } from "@/components/audit-json-view";

export interface AuditEvent {
  event_id?: string;
  schema_version?: string;
  correlation_id?: string;
  timestamp_utc?: string;
  host_id?: string;
  source_topic?: string;
  action?: { type?: string; outcome?: string; reason?: string };
  tool?: { name?: string; qualified?: string; server?: string; input_hash?: string; command?: string; arguments?: Record<string, unknown>; mitre?: { tactic: string; technique: string } };
  agent?: { name?: string; skill_id?: string };
  source?: { app?: string; tier?: string; adapter?: string };
  actor?: { type?: string; id?: string; role?: string };
  initiator?: { actor_type?: string; trigger?: string; operator_id?: string };
  model?: { id?: string; provider?: string };
  mcp?: { server_id?: string; tools?: string[] };
}

const ALL_SOURCES = ["blackbox", "cursor", "claude", "codex", "antigravity", "mcp_proxy"] as const;

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

function eventSourceApp(event: AuditEvent): string {
  if (event.source?.app) return event.source.app;
  if (event.agent?.name && event.agent.name !== "blackbox") return event.agent.name;
  return "blackbox";
}

const SOURCE_LABELS: Record<string, string> = {
  blackbox: "BLACKBOX",
  cursor: "Cursor",
  claude: "Claude",
  codex: "Codex",
  antigravity: "Antigravity",
  mcp_proxy: "MCP",
};

const ACTION_ICONS: Record<string, LucideIcon> = {
  session_start: Play,
  session_end: Square,
  tool_called: Wrench,
  approval_request: ShieldAlert,
  approval_response: ShieldCheck,
};

function shortCorr(id?: string): string {
  if (!id) return "—";
  return id.length > 8 ? `#${id.slice(-4)}` : id;
}

function shortHash(hash?: string): string {
  if (!hash) return "";
  return hash.length > 10 ? `${hash.slice(0, 6)}…` : hash;
}

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
  if (highlight) return "border-emerald-500/40 bg-violet-950/25";
  switch (outcome) {
    case "denied":
    case "error":
      return "border-red-900/50 bg-red-950/20";
    case "pending":
      return "border-amber-900/40 bg-amber-950/15";
    default:
      return "border-slate-300 dark:border-slate-800/60 bg-white dark:bg-slate-950/40";
  }
}

function copyText(text: string) {
  void navigator.clipboard?.writeText(text);
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

function SourceBadge({ app }: { app: string }) {
  const external = app !== "blackbox";
  return (
    <span
      className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${
        external
          ? "bg-sky-950/60 text-sky-300 ring-1 ring-sky-500/20"
          : "bg-violet-950/40 text-emerald-700 dark:text-emerald-300 ring-1 ring-emerald-500/20"
      }`}
    >
      {SOURCE_LABELS[app] || app}
    </span>
  );
}

function CopyChip({
  label,
  value,
  title,
}: {
  label: string;
  value: string;
  title?: string;
}) {
  return (
    <button
      type="button"
      className="group/chip flex shrink-0 items-center gap-0.5 rounded px-1 py-0.5 text-slate-500 dark:text-slate-400 opacity-70 transition hover:bg-slate-200 dark:bg-slate-800/80 hover:opacity-100"
      title={title ?? value}
      onClick={(e) => {
        e.stopPropagation();
        copyText(value);
      }}
    >
      <span>{label}</span>
      <Copy className="h-2.5 w-2.5 opacity-0 transition group-hover/chip:opacity-100" />
    </button>
  );
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
    render: (e) => (
      <div className="truncate text-slate-500 dark:text-slate-400 text-sm" title={e.tool?.mitre?.tactic || ""}>
        {e.tool?.mitre?.tactic ? (
          <span className="inline-flex items-center rounded-md bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-700 ring-1 ring-inset ring-emerald-600/20 dark:bg-emerald-400/10 dark:text-emerald-400 dark:ring-emerald-400/20">
            {e.tool.mitre.tactic.split(' ')[0]}
          </span>
        ) : "—"}
      </div>
    )
  },
  command: {
    id: "command", label: "Command", widthClass: "min-w-0 flex-1",
    render: (e) => <div className="truncate text-slate-500 dark:text-slate-400 font-mono text-sm" title={e.tool?.command || ""}>{e.tool?.command || "—"}</div>
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
    render: (e) => <div className="truncate text-slate-500 dark:text-slate-400 text-xs" title={e.correlation_id || ""}>{e.correlation_id || "—"}</div>
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

export const DEFAULT_COLUMNS: ColumnId[] = ["time", "action", "tool", "mitre", "command", "source", "actor", "model", "skill", "reason", "mcp_server", "host_id"];

function EventRow({ event, highlight, onViewSession, columns }: { event: AuditEvent; highlight: boolean; onViewSession?: (corrId: string) => void; columns: ColumnId[] }) {
  const [open, setOpen] = useState(false);
  const [showRawJson, setShowRawJson] = useState(false);
  const type = event.action?.type ?? "event";
  const outcome = event.action?.outcome ?? "";
  const sourceApp = eventSourceApp(event);
  const Icon = ACTION_ICONS[type] ?? XCircle;
  const detail =
    type === "tool_called" && event.tool?.command
      ? event.tool.command
      : type === "tool_called"
        ? event.tool?.qualified ?? ""
        : type.startsWith("approval")
          ? outcome
          : event.agent?.skill_id || sourceApp;

  return (
    <div
      className={`group/row rounded-lg border text-base font-mono transition ${rowOutcomeClass(outcome, highlight)}`}
    >
      <button
        type="button"
        className="flex w-full items-center gap-4 px-4 py-2 text-left hover:bg-slate-100 dark:bg-slate-900/30"
        onClick={() => setOpen(!open)}
      >
        <div className="w-4 shrink-0 text-slate-500 dark:text-slate-400">
          {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        </div>
        {columns.map(colId => {
          const c = COLUMN_REGISTRY[colId];
          if (!c) return null;
          return <div key={colId} className={`shrink-0 ${c.widthClass}`}>{c.render(event, formatTime, type, outcome, Icon, sourceApp)}</div>;
        })}
      </button>
      {open ? (
        <div className="relative border-t border-slate-300 dark:border-slate-800/60 px-4 py-4 bg-white dark:bg-slate-950/20">
          <div className="grid grid-cols-2 gap-x-6 gap-y-3 mb-5 max-w-4xl">
            <div className="flex flex-col gap-1">
              <span className="text-sm uppercase tracking-wider text-slate-500 dark:text-slate-400">Timestamp</span>
              <span className="text-slate-800 dark:text-slate-200">{event.timestamp_utc || "—"}</span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-sm uppercase tracking-wider text-slate-500 dark:text-slate-400">Event ID</span>
              <span className="text-slate-800 dark:text-slate-200">{event.event_id || "—"}</span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-sm uppercase tracking-wider text-slate-500 dark:text-slate-400">Action</span>
              <span className="text-slate-800 dark:text-slate-200">{event.action?.type || "—"}</span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-sm uppercase tracking-wider text-slate-500 dark:text-slate-400">Outcome</span>
              <span className="text-slate-800 dark:text-slate-200">{event.action?.outcome || "—"} {event.action?.reason && <span className="text-slate-500 dark:text-slate-400 text-sm">({event.action.reason})</span>}</span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-sm uppercase tracking-wider text-slate-500 dark:text-slate-400">Tool</span>
              <span className="text-slate-800 dark:text-slate-200">{event.tool?.qualified || event.tool?.name || "—"}</span>
            </div>
            {event.tool?.mitre?.tactic && (
              <div className="flex flex-col gap-1">
                <span className="text-sm uppercase tracking-wider text-slate-500 dark:text-slate-400">MITRE ATT&CK</span>
                <span className="text-slate-800 dark:text-slate-200">
                  {event.tool.mitre.tactic} 
                  <span className="text-slate-500 dark:text-slate-400 text-sm ml-1">({event.tool.mitre.technique})</span>
                </span>
              </div>
            )}
            <div className="flex flex-col gap-1">
              <span className="text-sm uppercase tracking-wider text-slate-500 dark:text-slate-400">Source</span>
              <span className="text-slate-800 dark:text-slate-200">{event.source?.app || "—"} ({event.source?.tier || "—"})</span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-sm uppercase tracking-wider text-slate-500 dark:text-slate-400">Actor</span>
              <span className="text-slate-800 dark:text-slate-200">{event.actor?.id || "—"}</span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-sm uppercase tracking-wider text-slate-500 dark:text-slate-400">Initiator</span>
              <span className="text-slate-800 dark:text-slate-200">{event.initiator?.operator_id || "—"}</span>
            </div>
            <div className="flex flex-col gap-1 col-span-2">
              <span className="text-sm uppercase tracking-wider text-slate-500 dark:text-slate-400">Correlation ID</span>
              <div className="flex items-center gap-2">
                <span className="text-slate-800 dark:text-slate-200">{event.correlation_id || "—"}</span>
                {event.correlation_id && onViewSession && (
                  <button
                    type="button"
                    onClick={() => onViewSession(event.correlation_id!)}
                    className="rounded border border-sky-500/30 bg-sky-950/30 px-2 py-0.5 text-sm text-sky-300 transition hover:bg-sky-900/40"
                  >
                    View Full Session
                  </button>
                )}
              </div>
            </div>
          </div>
          
          {event.tool?.command && (
            <div className="mb-5 max-w-4xl">
              <span className="text-sm uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-1 block">Command</span>
              <pre className="bg-white dark:bg-slate-950 border border-slate-300 dark:border-slate-800/80 rounded p-3 text-slate-700 dark:text-slate-300 overflow-x-auto">
                {event.tool.command}
              </pre>
            </div>
          )}

          {event.tool?.arguments && Object.keys(event.tool.arguments).length > 0 && !event.tool?.command && (
            <div className="mb-5 max-w-4xl">
              <span className="text-sm uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-1 block">Arguments</span>
              <pre className="bg-white dark:bg-slate-950 border border-slate-300 dark:border-slate-800/80 rounded p-3 text-slate-700 dark:text-slate-300 overflow-x-auto text-sm max-h-40">
                {JSON.stringify(event.tool.arguments, null, 2)}
              </pre>
            </div>
          )}

          <div className="flex items-center gap-2">
            <button
              type="button"
              className={`inline-flex items-center gap-1.5 rounded border px-2 py-1 text-sm transition ${showRawJson ? 'border-emerald-500/50 bg-emerald-900/20 text-emerald-700 dark:text-emerald-300' : 'border-slate-400 dark:border-slate-700 bg-slate-100 dark:bg-slate-900 text-slate-500 dark:text-slate-400 hover:bg-slate-200 dark:bg-slate-800 hover:text-slate-900 dark:hover:text-slate-800 dark:text-slate-200'}`}
              onClick={() => setShowRawJson(!showRawJson)}
            >
              <Wrench className="h-3 w-3" />
              {showRawJson ? "Hide Raw JSON" : "Show Raw JSON"}
            </button>
            <button
              type="button"
              className="inline-flex items-center gap-1.5 rounded border border-slate-400 dark:border-slate-700 bg-slate-100 dark:bg-slate-900 px-2 py-1 text-sm text-slate-500 dark:text-slate-400 transition hover:bg-slate-200 dark:bg-slate-800 hover:text-slate-900 dark:hover:text-slate-800 dark:text-slate-200"
              onClick={() => copyText(JSON.stringify(event, null, 2))}
            >
              <Copy className="h-3 w-3" />
              Copy
            </button>
          </div>

          {showRawJson && (
            <div className="mt-4 border-t border-slate-300 dark:border-slate-800/60 pt-4">
              <AuditJsonView value={event} />
            </div>
          )}
        </div>
      ) : null}
    </div>
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
      className={`rounded px-2 py-0.5 text-sm transition ${
        active
          ? "bg-emerald-900/50 text-emerald-800 dark:text-emerald-200 ring-1 ring-emerald-500/30"
          : "bg-slate-100 dark:bg-slate-900 text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:text-slate-300"
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
      const saved = localStorage.getItem("blackbox-columns-v2");
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
    localStorage.setItem("blackbox-columns-v2", JSON.stringify(newCols));
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

  useEffect(() => {
    setLoading(true);
    void fetchTail();
  }, [fetchTail, runsRefreshKey, timeWindowIdx, devMode, sessionId]);

  useEffect(() => {
    if (!atLatest) return;
    const timer = window.setInterval(() => void fetchPage("latest"), 8000);
    return () => window.clearInterval(timer);
  }, [atLatest, fetchPage]);

  const filteredEvents = useMemo(() => {
    const q = debouncedSearchQuery.trim().toLowerCase();
    return events.filter((ev) => {
      if (sourceFilter !== "all" && eventSourceApp(ev) !== sourceFilter) return false;
      const type = ev.action?.type ?? "";
      if (eventTypeFilter !== "all" && type !== eventTypeFilter) return false;
      const outcome = ev.action?.outcome ?? "";
      const isIssue = outcome === "denied" || outcome === "error";
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

  const toggleOutcome = (key: keyof typeof outcomeFilters) => {
    setOutcomeFilters((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col rounded-xl border border-slate-300 dark:border-slate-800/60 bg-white dark:bg-slate-950/50">
      <div className="space-y-2 border-b border-slate-300 dark:border-slate-800/60 px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Radio className="h-4 w-4 text-emerald-400" />
            <div>
              <p className="text-lg font-semibold text-slate-900 dark:text-slate-100">Flight recorder</p>
              <p className="text-sm text-slate-500 dark:text-slate-400">
                {filteredEvents.length} shown · Tier A + B
                {!atLatest ? " · viewing history" : ""}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <button
              type="button"
              className="inline-flex items-center gap-1.5 text-sm uppercase tracking-wider text-slate-500 dark:text-slate-400 transition hover:text-slate-700 dark:text-slate-300"
              onClick={() => {
                if (filteredEvents.length === 0) return;
                const jsonl = filteredEvents.map((ev) => JSON.stringify(ev)).join("\n");
                const blob = new Blob([jsonl], { type: "application/jsonl" });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = `audit-export-${new Date().toISOString()}.jsonl`;
                a.click();
                URL.revokeObjectURL(url);
              }}
              title="Export current view to JSONL"
            >
              <Download className="h-3 w-3" />
              JSONL
            </button>
            <button
              type="button"
              className="inline-flex items-center gap-1.5 text-sm uppercase tracking-wider text-slate-500 dark:text-slate-400 transition hover:text-slate-700 dark:text-slate-300"
              onClick={() => {
                if (filteredEvents.length === 0) return;
                const headers = ["Time", "Event ID", "Action", "Outcome", "Tool", "Command", "Source App", "Actor ID", "Correlation ID"];
                const rows = filteredEvents.map(ev => {
                  return [
                    ev.timestamp_utc || "",
                    ev.event_id || "",
                    ev.action?.type || "",
                    ev.action?.outcome || "",
                    ev.tool?.qualified || ev.tool?.name || "",
                    ev.tool?.command || "",
                    eventSourceApp(ev),
                    ev.actor?.id || "",
                    ev.correlation_id || ""
                  ].map(field => `"${String(field).replace(/"/g, '""')}"`).join(",");
                });
                const csv = [headers.join(","), ...rows].join("\n");
                const blob = new Blob([csv], { type: "text/csv" });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = `audit-export-${new Date().toISOString()}.csv`;
                a.click();
                URL.revokeObjectURL(url);
              }}
              title="Export current view to CSV"
            >
              CSV
            </button>
            <div className="relative">
              <button
                onClick={() => setShowColumnManager(!showColumnManager)}
                className="flex items-center gap-1.5 rounded-md border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-300 hover:bg-slate-700 transition"
                title="Manage Columns"
              >
                <Settings2 className="h-3.5 w-3.5" />
                <span>Columns</span>
              </button>
              {showColumnManager && (
                <div className="absolute right-0 top-full mt-2 w-64 rounded-md border border-slate-700 bg-slate-800 p-2 shadow-xl z-50">
                  <div className="mb-2 px-2 text-xs font-semibold text-slate-400">Manage Columns</div>
                  <div className="flex flex-col gap-1 max-h-64 overflow-y-auto">
                    {[...columns, ...(Object.keys(COLUMN_REGISTRY) as ColumnId[]).filter(k => !columns.includes(k))].map((colId) => {
                      const c = COLUMN_REGISTRY[colId];
                      const isActive = columns.includes(colId);
                      const idx = columns.indexOf(colId);
                      
                      return (
                        <div key={colId} className="flex items-center justify-between rounded px-2 py-1.5 hover:bg-slate-700/50">
                          <div className="flex items-center gap-2">
                            <button
                              onClick={() => {
                                if (isActive) {
                                  updateColumns(columns.filter(x => x !== colId));
                                } else {
                                  updateColumns([...columns, colId]);
                                }
                              }}
                              className={`flex h-4 w-4 items-center justify-center rounded border ${isActive ? 'border-emerald-500 bg-emerald-500/20 text-emerald-400' : 'border-slate-500 text-transparent'}`}
                            >
                              {isActive && <Eye className="h-3 w-3" />}
                              {!isActive && <EyeOff className="h-3 w-3 text-slate-500" />}
                            </button>
                            <span className="text-xs text-slate-300">{c.label}</span>
                          </div>
                          {isActive && (
                            <div className="flex gap-1">
                              <button
                                disabled={idx === 0}
                                onClick={() => {
                                  const newCols = [...columns];
                                  const temp = newCols[idx - 1];
                                  newCols[idx - 1] = newCols[idx];
                                  newCols[idx] = temp;
                                  updateColumns(newCols);
                                }}
                                className="text-slate-400 hover:text-white disabled:opacity-30"
                              >
                                <ArrowUp className="h-3 w-3" />
                              </button>
                              <button
                                disabled={idx === columns.length - 1}
                                onClick={() => {
                                  const newCols = [...columns];
                                  const temp = newCols[idx + 1];
                                  newCols[idx + 1] = newCols[idx];
                                  newCols[idx] = temp;
                                  updateColumns(newCols);
                                }}
                                className="text-slate-400 hover:text-white disabled:opacity-30"
                              >
                                <ArrowDown className="h-3 w-3" />
                              </button>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
            <button
              type="button"
              className="text-sm uppercase tracking-wider text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:text-slate-300"
              onClick={() => void fetchTail()}
            >
              Refresh
            </button>
          </div>
        </div>

        <div className="relative">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-slate-500 dark:text-slate-600" />
          <input
            type="search"
            placeholder="Search corr, tool, command, hash…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full rounded border border-slate-300 dark:border-slate-800 bg-white dark:bg-slate-950 py-1.5 pl-7 pr-2 text-base text-slate-700 dark:text-slate-300 placeholder:text-slate-500 dark:text-slate-600 focus:border-emerald-500/40 focus:outline-none"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <select
            className="rounded border border-slate-300 dark:border-slate-800 bg-white dark:bg-slate-950 px-2 py-1 text-sm text-slate-500 dark:text-slate-400"
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value)}
          >
            <option value="all">All sources</option>
            {ALL_SOURCES.map((s) => (
              <option key={s} value={s}>
                {SOURCE_LABELS[s]}
              </option>
            ))}
          </select>

          <select
            className="rounded border border-slate-300 dark:border-slate-800 bg-white dark:bg-slate-950 px-2 py-1 text-sm text-slate-500 dark:text-slate-400"
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

          <div className="flex items-center gap-1">
            {TIME_WINDOWS.map((w, i) => (
              <FilterChip
                key={w.label}
                active={timeWindowIdx === i}
                label={w.label}
                onClick={() => setTimeWindowIdx(i)}
              />
            ))}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[10px] uppercase tracking-wide text-slate-500 dark:text-slate-600">Outcome</span>
          <FilterChip active={outcomeFilters.success} label="OK" onClick={() => toggleOutcome("success")} />
          <FilterChip
            active={outcomeFilters.pending}
            label="Pending"
            onClick={() => toggleOutcome("pending")}
          />
          <FilterChip
            active={outcomeFilters.issues}
            label="Denied / Error"
            onClick={() => toggleOutcome("issues")}
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-1.5 overflow-y-auto p-3">
        {loading && filteredEvents.length === 0 ? (
          <p className="py-8 text-center text-lg text-slate-500 dark:text-slate-400">Loading audit events…</p>
        ) : error && filteredEvents.length === 0 ? (
          <p className="py-8 text-center text-lg text-red-400/90">{error}</p>
        ) : filteredEvents.length === 0 ? (
          <p className="py-8 text-center text-lg text-slate-500 dark:text-slate-400">
            No events match filters. Try <span className="font-mono text-slate-500 dark:text-slate-400">All</span> time
            window or a Tier B source (Cursor, Antigravity).
          </p>
        ) : (
          <>
            <div className="flex w-full items-center gap-4 px-4 py-1.5 text-left text-sm uppercase tracking-wider text-slate-500 dark:text-slate-400 font-semibold mb-1">
              <div className="w-4 shrink-0"></div>
              {columns.map(colId => {
                const c = COLUMN_REGISTRY[colId];
                if (!c) return null;
                return (
                  <div 
                    key={colId} 
                    className={`shrink-0 cursor-grab hover:text-emerald-400 dark:hover:text-emerald-400 transition select-none ${c.widthClass} ${draggedCol === colId ? 'opacity-50' : ''}`}
                    draggable={true}
                    onDragStart={(e) => handleDragStart(e, colId)}
                    onDragOver={handleDragOver}
                    onDrop={(e) => handleDrop(e, colId)}
                    onDragEnd={() => setDraggedCol(null)}
                    title={`Drag to reorder ${c.label}`}
                  >
                    {c.label}
                  </div>
                );
              })}
            </div>
            {filteredEvents.map((ev, i) => (
              <EventRow columns={columns}
                key={eventKey(ev) || `${i}`}
                event={ev}
                highlight={!!threadId && ev.correlation_id === threadId}
                onViewSession={(corrId) => {
                  setSearchQuery(corrId);
                  window.scrollTo({ top: 0, behavior: 'smooth' });
                }}
              />
            ))}
          </>
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-300 dark:border-slate-800/60 px-4 py-2">
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            disabled={!pagination.has_older || loadingOlder}
            onClick={() => void loadOlder()}
            className="inline-flex items-center gap-1 rounded border border-slate-300 dark:border-slate-800 bg-white dark:bg-slate-950 px-2 py-1 text-sm text-slate-500 dark:text-slate-400 transition hover:border-slate-400 dark:border-slate-700 hover:text-slate-900 dark:hover:text-slate-800 dark:text-slate-200 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <ChevronLeft className="h-3 w-3" />
            Older
          </button>
          <button
            type="button"
            disabled={!pagination.has_newer || loadingNewer}
            onClick={() => void loadNewer()}
            className="inline-flex items-center gap-1 rounded border border-slate-300 dark:border-slate-800 bg-white dark:bg-slate-950 px-2 py-1 text-sm text-slate-500 dark:text-slate-400 transition hover:border-slate-400 dark:border-slate-700 hover:text-slate-900 dark:hover:text-slate-800 dark:text-slate-200 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Newer
            <ChevronRight className="h-3 w-3" />
          </button>
          {!atLatest ? (
            <button
              type="button"
              onClick={() => void jumpToLatest()}
              className="rounded border border-emerald-500/30 bg-violet-950/30 px-2 py-1 text-sm text-emerald-800 dark:text-emerald-200 transition hover:bg-emerald-900/40"
            >
              Latest
            </button>
          ) : null}
        </div>
        <p className="text-sm text-slate-500 dark:text-slate-600">
          Tier B records agents you wire in (hooks, MCP proxy).
        </p>
      </div>
    </div>
  );
}
