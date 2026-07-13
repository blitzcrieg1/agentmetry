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
  action?: { type?: string; outcome?: string };
  tool?: { qualified?: string; server?: string; input_hash?: string; command?: string; arguments?: Record<string, unknown> };
  agent?: { name?: string; skill_id?: string };
  source?: { app?: string; tier?: string; adapter?: string };
  actor?: { id?: string };
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
      return "bg-zinc-500";
  }
}

function rowOutcomeClass(outcome?: string, highlight?: boolean): string {
  if (highlight) return "border-violet-500/40 bg-violet-950/25";
  switch (outcome) {
    case "denied":
    case "error":
      return "border-red-900/50 bg-red-950/20";
    case "pending":
      return "border-amber-900/40 bg-amber-950/15";
    default:
      return "border-zinc-800/60 bg-zinc-950/40";
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
      className={`shrink-0 rounded px-1.5 py-0.5 text-[9px] uppercase tracking-wide ${
        external
          ? "bg-sky-950/60 text-sky-300 ring-1 ring-sky-500/20"
          : "bg-violet-950/40 text-violet-300 ring-1 ring-violet-500/20"
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
      className="group/chip flex shrink-0 items-center gap-0.5 rounded px-1 py-0.5 text-zinc-500 opacity-70 transition hover:bg-zinc-800/80 hover:opacity-100"
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

function EventRow({ event, highlight }: { event: AuditEvent; highlight: boolean }) {
  const [open, setOpen] = useState(false);
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
      className={`group/row rounded-lg border text-xs font-mono transition ${rowOutcomeClass(outcome, highlight)}`}
    >
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-zinc-900/30"
        onClick={() => setOpen(!open)}
      >
        {open ? (
          <ChevronDown className="h-3 w-3 shrink-0 text-zinc-500" />
        ) : (
          <ChevronRight className="h-3 w-3 shrink-0 text-zinc-500" />
        )}
        <span className="w-16 shrink-0 text-zinc-500">{formatTime(event.timestamp_utc)}</span>
        <SourceBadge app={sourceApp} />
        <span className={`h-2 w-2 shrink-0 rounded-full ${outcomeDot(outcome)}`} />
        <span className="flex w-28 shrink-0 items-center gap-1 truncate text-violet-300">
          <Icon className="h-3 w-3 shrink-0 text-violet-400/80" />
          <span className="truncate">{type}</span>
        </span>
        <span className="min-w-0 flex-1 truncate text-zinc-300" title={detail}>
          {detail}
        </span>
        {event.correlation_id ? (
          <CopyChip label={shortCorr(event.correlation_id)} value={event.correlation_id} />
        ) : null}
        {event.tool?.input_hash ? (
          <CopyChip
            label={shortHash(event.tool.input_hash)}
            value={event.tool.input_hash}
            title={`sha256 ${event.tool.input_hash}`}
          />
        ) : null}
      </button>
      {open ? (
        <div className="relative border-t border-zinc-800/60 px-3 py-2">
          <button
            type="button"
            className="absolute right-3 top-3 inline-flex items-center gap-1.5 rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-[10px] text-zinc-400 transition hover:bg-zinc-800 hover:text-zinc-200"
            onClick={() => copyText(JSON.stringify(event, null, 2))}
          >
            <Copy className="h-3 w-3" />
            Copy raw JSON
          </button>
          <AuditJsonView value={event} />
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
      className={`rounded px-2 py-0.5 text-[10px] transition ${
        active
          ? "bg-violet-900/50 text-violet-200 ring-1 ring-violet-500/30"
          : "bg-zinc-900 text-zinc-500 hover:text-zinc-300"
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
    <div className="flex min-h-0 flex-1 flex-col rounded-xl border border-zinc-800/60 bg-zinc-950/50">
      <div className="space-y-2 border-b border-zinc-800/60 px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Radio className="h-4 w-4 text-violet-400" />
            <div>
              <p className="text-sm font-semibold text-zinc-100">Flight recorder</p>
              <p className="text-[10px] text-zinc-500">
                {filteredEvents.length} shown · Tier A + B
                {!atLatest ? " · viewing history" : ""}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <button
              type="button"
              className="inline-flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-zinc-500 transition hover:text-zinc-300"
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
              Export JSONL
            </button>
            <button
              type="button"
              className="text-[10px] uppercase tracking-wider text-zinc-500 hover:text-zinc-300"
              onClick={() => void fetchTail()}
            >
              Refresh
            </button>
          </div>
        </div>

        <div className="relative">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-zinc-600" />
          <input
            type="search"
            placeholder="Search corr, tool, command, hash…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full rounded border border-zinc-800 bg-zinc-950 py-1.5 pl-7 pr-2 text-[11px] text-zinc-300 placeholder:text-zinc-600 focus:border-violet-500/40 focus:outline-none"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <select
            className="rounded border border-zinc-800 bg-zinc-950 px-2 py-1 text-[10px] text-zinc-400"
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
            className="rounded border border-zinc-800 bg-zinc-950 px-2 py-1 text-[10px] text-zinc-400"
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
          <span className="text-[9px] uppercase tracking-wide text-zinc-600">Outcome</span>
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
          <p className="py-8 text-center text-sm text-zinc-500">Loading audit events…</p>
        ) : error && filteredEvents.length === 0 ? (
          <p className="py-8 text-center text-sm text-red-400/90">{error}</p>
        ) : filteredEvents.length === 0 ? (
          <p className="py-8 text-center text-sm text-zinc-500">
            No events match filters. Try <span className="font-mono text-zinc-400">All</span> time
            window or a Tier B source (Cursor, Antigravity).
          </p>
        ) : (
          filteredEvents.map((ev, i) => (
            <EventRow
              key={eventKey(ev) || `${i}`}
              event={ev}
              highlight={!!threadId && ev.correlation_id === threadId}
            />
          ))
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-zinc-800/60 px-4 py-2">
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            disabled={!pagination.has_older || loadingOlder}
            onClick={() => void loadOlder()}
            className="inline-flex items-center gap-1 rounded border border-zinc-800 bg-zinc-950 px-2 py-1 text-[10px] text-zinc-400 transition hover:border-zinc-700 hover:text-zinc-200 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <ChevronLeft className="h-3 w-3" />
            Older
          </button>
          <button
            type="button"
            disabled={!pagination.has_newer || loadingNewer}
            onClick={() => void loadNewer()}
            className="inline-flex items-center gap-1 rounded border border-zinc-800 bg-zinc-950 px-2 py-1 text-[10px] text-zinc-400 transition hover:border-zinc-700 hover:text-zinc-200 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Newer
            <ChevronRight className="h-3 w-3" />
          </button>
          {!atLatest ? (
            <button
              type="button"
              onClick={() => void jumpToLatest()}
              className="rounded border border-violet-500/30 bg-violet-950/30 px-2 py-1 text-[10px] text-violet-200 transition hover:bg-violet-900/40"
            >
              Latest
            </button>
          ) : null}
        </div>
        <p className="text-[10px] text-zinc-600">
          Tier B records agents you wire in (hooks, MCP proxy).
        </p>
      </div>
    </div>
  );
}
