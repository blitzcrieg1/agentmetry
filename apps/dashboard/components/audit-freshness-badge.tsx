"use client";

import { useEffect, useState } from "react";
import { ORCHESTRATOR_URL } from "@/lib/utils";
import { apiHeaders } from "@/lib/api";

interface AuditStatus {
  enabled: boolean;
  last_event_utc: string | null;
  recent: number;
  by_source: Record<string, number>;
}

const SOURCE_ORDER = ["blackbox", "cursor", "claude", "codex", "antigravity", "mcp_proxy"] as const;

const SOURCE_SHORT: Record<string, string> = {
  blackbox: "BB",
  cursor: "Cu",
  claude: "Cl",
  codex: "Cx",
  antigravity: "Ag",
  mcp_proxy: "MCP",
};

/** Stale if no event in this many minutes (operator idle is OK; hooks dead is not). */
const STALE_MINUTES = 15;

function minutesSince(iso: string | null): number | null {
  if (!iso) return null;
  const ms = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(ms)) return null;
  return Math.max(0, Math.floor(ms / 60_000));
}

function freshnessLabel(minutes: number | null, enabled: boolean, recent: number): string {
  if (!enabled) return "Audit export off";
  if (minutes === null || recent === 0) return "No events yet";
  if (minutes === 0) return "Last event just now";
  if (minutes === 1) return "Last event 1 min ago";
  return `Last event ${minutes} min ago`;
}

export function AuditFreshnessBadge() {
  const [status, setStatus] = useState<AuditStatus | null>(null);

  useEffect(() => {
    const load = () => {
      fetch(`${ORCHESTRATOR_URL}/api/v1/audit/status`, { headers: apiHeaders() })
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => setStatus(data))
        .catch(() => setStatus(null));
    };
    load();
    const timer = window.setInterval(load, 30_000);
    return () => window.clearInterval(timer);
  }, []);

  const enabled = status?.enabled ?? false;
  const minutes = minutesSince(status?.last_event_utc ?? null);
  const recent = status?.recent ?? 0;
  const bySource = status?.by_source ?? {};

  const stale = !enabled || (recent > 0 && minutes !== null && minutes > STALE_MINUTES);

  const tone = !enabled
    ? "border-red-500/40 bg-red-950/30 text-red-300"
    : stale
      ? "border-amber-500/40 bg-amber-950/30 text-amber-300"
      : recent === 0
        ? "border-zinc-700/60 bg-zinc-950/40 text-zinc-400"
        : "border-emerald-500/30 bg-emerald-950/40 text-emerald-300";

  const label = freshnessLabel(minutes, enabled, recent);

  return (
    <div
      className={`hidden items-center gap-2 rounded-full border px-2.5 py-1 sm:flex ${tone}`}
      title={
        enabled
          ? `Audit export on · ${recent} events in tail window`
          : "Set BLACKBOX_AUDIT_EXPORT_ENABLED=1"
      }
    >
      <span className="text-[10px] font-medium">{label}</span>
      <span className="flex items-center gap-0.5">
        {SOURCE_ORDER.map((src) => {
          const count = bySource[src] ?? 0;
          const active = count > 0;
          return (
            <span
              key={src}
              className={`h-1.5 w-1.5 rounded-full ${
                active ? "bg-emerald-400" : "bg-zinc-600"
              }`}
              title={`${src}: ${count} recent`}
            />
          );
        })}
      </span>
      <span className="hidden text-[9px] uppercase tracking-wider text-zinc-500 lg:inline">
        {SOURCE_ORDER.filter((s) => (bySource[s] ?? 0) > 0)
          .map((s) => SOURCE_SHORT[s] ?? s)
          .join(" · ") || "—"}
      </span>
    </div>
  );
}
