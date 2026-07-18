"use client";

import { useEffect, useState } from "react";
import { ORCHESTRATOR_URL } from "@/lib/utils";
import { apiHeaders } from "@/lib/api";
import { sourceDotClass } from "@/lib/audit-source";

interface AuditStatus {
  enabled: boolean;
  last_event_utc: string | null;
  recent: number;
  by_source: Record<string, number>;
}

const SOURCE_ORDER = ["agentmetry", "claude", "cursor", "codex", "antigravity", "mcp_proxy"] as const;

const STALE_MINUTES = 15;

function minutesSince(iso: string | null): number | null {
  if (!iso) return null;
  const ms = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(ms)) return null;
  return Math.max(0, Math.floor(ms / 60_000));
}

function ingestLabel(minutes: number | null, enabled: boolean, recent: number): string {
  if (!enabled) return "Ingest off";
  if (minutes === null || recent === 0) return "No events yet";
  if (minutes === 0) return "Ingest live";
  if (minutes === 1) return "Last event 1m ago";
  return `Last event ${minutes}m ago`;
}

export function FeedStatusBar({ wsConnected }: { wsConnected: boolean }) {
  const [status, setStatus] = useState<AuditStatus | null>(null);
  // Backend down and ingest disabled are opposite diagnoses; a fetch failure
  // must not render as "Ingest off".
  const [unreachable, setUnreachable] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    const load = () => {
      fetch(`${ORCHESTRATOR_URL}/api/v1/audit/status`, { headers: apiHeaders() })
        .then((r) => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.json();
        })
        .then((data) => {
          setStatus(data);
          setUnreachable(false);
        })
        .catch(() => {
          setStatus(null);
          setUnreachable(true);
        })
        .finally(() => setLoaded(true));
    };
    load();
    const timer = window.setInterval(load, 30_000);
    return () => window.clearInterval(timer);
  }, []);

  if (!loaded) {
    return (
      <div className="flex items-center gap-2 font-mono text-xs text-muted-foreground">
        <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-muted-foreground/50" />
        Checking feed…
      </div>
    );
  }

  if (unreachable) {
    return (
      <div className="flex items-center gap-2 font-mono text-xs text-red-500 dark:text-red-400" title={`No response from ${ORCHESTRATOR_URL}`}>
        <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-red-500 dark:bg-red-400" />
        Backend unreachable
      </div>
    );
  }

  const enabled = status?.enabled ?? false;
  const minutes = minutesSince(status?.last_event_utc ?? null);
  const recent = status?.recent ?? 0;
  const bySource = status?.by_source ?? {};
  const stale = !enabled || (recent > 0 && minutes !== null && minutes > STALE_MINUTES);
  const label = ingestLabel(minutes, enabled, recent);

  const ingestTone = !enabled
    ? "text-red-600 dark:text-red-400"
    : stale
      ? "text-amber-600 dark:text-amber-400"
      : recent === 0
        ? "text-muted-foreground"
        : "text-emerald-600 dark:text-emerald-400";

  const ingestDot = !enabled
    ? "bg-red-500 dark:bg-red-400"
    : stale
      ? "bg-amber-500 dark:bg-amber-400"
      : recent === 0
        ? "bg-muted-foreground"
        : "bg-emerald-500 dark:bg-emerald-400 animate-pulse";

  return (
    <div
      className="flex items-center gap-2 font-mono text-xs"
      title={
        enabled
          ? `Audit ingest · ${recent} events in tail window`
          : "Set AGENTMETRY_AUDIT_EXPORT_ENABLED=1"
      }
    >
      <span className={`inline-flex items-center gap-1.5 ${ingestTone}`}>
        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${ingestDot}`} />
        {label}
      </span>

      <span className="hidden text-border sm:inline">·</span>

      <span className="hidden items-center gap-1 sm:inline-flex" title="Recent events by hook source">
        {SOURCE_ORDER.map((src) => {
          const count = bySource[src] ?? 0;
          return (
            <span
              key={src}
              className={`h-1.5 w-1.5 rounded-full ${sourceDotClass(src, count > 0)}`}
              title={`${src}: ${count}`}
            />
          );
        })}
      </span>

      {wsConnected ? (
        <>
          <span className="hidden text-border md:inline">·</span>
          <span
            className="hidden items-center gap-1 text-emerald-400/80 md:inline-flex"
            title="Run stream connected (WebSocket)"
          >
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400/60" />
            Runs
          </span>
        </>
      ) : null}
    </div>
  );
}
