"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Radio } from "lucide-react";
import { useAgentStore } from "@/lib/store";
import { ORCHESTRATOR_URL } from "@/lib/utils";

export interface AuditEvent {
  schema_version?: string;
  correlation_id?: string;
  timestamp_utc?: string;
  action?: { type?: string; outcome?: string };
  tool?: { qualified?: string; server?: string; input_hash?: string };
  agent?: { skill_id?: string };
  actor?: { id?: string };
}

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
      return "bg-amber-400";
    default:
      return "bg-zinc-500";
  }
}

function copyText(text: string) {
  void navigator.clipboard?.writeText(text);
}

function EventRow({ event, highlight }: { event: AuditEvent; highlight: boolean }) {
  const [open, setOpen] = useState(false);
  const type = event.action?.type ?? "event";
  const outcome = event.action?.outcome ?? "";
  const detail =
    type === "tool_called"
      ? event.tool?.qualified ?? ""
      : type.startsWith("approval")
        ? outcome
        : event.agent?.skill_id ?? "";

  return (
    <div
      className={`rounded-lg border text-xs font-mono ${
        highlight
          ? "border-violet-500/40 bg-violet-950/20"
          : "border-zinc-800/60 bg-zinc-950/40"
      }`}
    >
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-zinc-900/40"
        onClick={() => setOpen(!open)}
      >
        {open ? (
          <ChevronDown className="h-3 w-3 shrink-0 text-zinc-500" />
        ) : (
          <ChevronRight className="h-3 w-3 shrink-0 text-zinc-500" />
        )}
        <span className="w-16 shrink-0 text-zinc-500">{formatTime(event.timestamp_utc)}</span>
        <span className={`h-2 w-2 shrink-0 rounded-full ${outcomeDot(outcome)}`} />
        <span className="w-28 shrink-0 truncate text-violet-300">{type}</span>
        <span className="min-w-0 flex-1 truncate text-zinc-300">{detail}</span>
        <span
          className="shrink-0 text-zinc-500"
          title={event.correlation_id}
          onClick={(e) => {
            e.stopPropagation();
            if (event.correlation_id) copyText(event.correlation_id);
          }}
        >
          {shortCorr(event.correlation_id)}
        </span>
        {event.tool?.input_hash ? (
          <span
            className="shrink-0 text-zinc-600"
            title={event.tool.input_hash}
            onClick={(e) => {
              e.stopPropagation();
              copyText(event.tool!.input_hash!);
            }}
          >
            {shortHash(event.tool.input_hash)}
          </span>
        ) : null}
      </button>
      {open ? (
        <pre className="max-h-40 overflow-auto border-t border-zinc-800/60 px-3 py-2 text-[10px] leading-relaxed text-zinc-400">
          {JSON.stringify(event, null, 2)}
        </pre>
      ) : null}
    </div>
  );
}

export function FlightRecorderPanel() {
  const threadId = useAgentStore((s) => s.threadId);
  const runsRefreshKey = useAgentStore((s) => s.runsRefreshKey);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchTail = useCallback(async () => {
    try {
      const res = await fetch(`${ORCHESTRATOR_URL}/api/v1/audit/tail?limit=50`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setEvents(data.events ?? []);
      setError(null);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchTail();
    const timer = window.setInterval(() => void fetchTail(), 8000);
    return () => window.clearInterval(timer);
  }, [fetchTail, runsRefreshKey]);

  return (
    <div className="flex min-h-0 flex-1 flex-col rounded-xl border border-zinc-800/60 bg-zinc-950/50">
      <div className="flex items-center justify-between border-b border-zinc-800/60 px-4 py-3">
        <div className="flex items-center gap-2">
          <Radio className="h-4 w-4 text-violet-400" />
          <div>
            <p className="text-sm font-semibold text-zinc-100">Flight recorder</p>
            <p className="text-[10px] text-zinc-500">Local audit trail · Pipe 2</p>
          </div>
        </div>
        <button
          type="button"
          className="text-[10px] uppercase tracking-wider text-zinc-500 hover:text-zinc-300"
          onClick={() => void fetchTail()}
        >
          Refresh
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-1.5 overflow-y-auto p-3">
        {loading && events.length === 0 ? (
          <p className="py-8 text-center text-sm text-zinc-500">Loading audit events…</p>
        ) : error && events.length === 0 ? (
          <p className="py-8 text-center text-sm text-red-400/90">{error}</p>
        ) : events.length === 0 ? (
          <p className="py-8 text-center text-sm text-zinc-500">
            No events yet. Run a skill — tool calls and approvals appear here as they happen.
          </p>
        ) : (
          events.map((ev, i) => (
            <EventRow
              key={`${ev.correlation_id}-${ev.timestamp_utc}-${i}`}
              event={ev}
              highlight={!!threadId && ev.correlation_id === threadId}
            />
          ))
        )}
      </div>

      <p className="border-t border-zinc-800/60 px-4 py-2 text-[10px] text-zinc-600">
        Tier A only — records agents through this host. Unmanaged copilots on the same machine are
        a CASB problem, not this.
      </p>
    </div>
  );
}
