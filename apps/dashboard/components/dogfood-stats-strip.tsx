"use client";

import { useEffect, useState } from "react";
import { ORCHESTRATOR_URL } from "@/lib/utils";
import { apiHeaders } from "@/lib/api";
import { sourceLabel } from "@/lib/audit-source";

type AuditStats = {
  enabled: boolean;
  window_days?: number;
  total_events?: number;
  sessions?: number;
  detections?: number;
  denied?: number;
  dlp_matches?: number;
  tool_policy_hits?: number;
  tool_policy_blocks?: number;
  by_source?: Record<string, number>;
  last_event_utc?: string | null;
};

function StatPill({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="rounded-md border border-border bg-card px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={`text-lg font-semibold tabular-nums ${accent ? "text-amber-500" : ""}`}>{value}</div>
    </div>
  );
}

export function DogfoodStatsStrip() {
  const [stats, setStats] = useState<AuditStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const res = await fetch(`${ORCHESTRATOR_URL}/api/v1/audit/stats?days=7`, {
          headers: apiHeaders(),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        setStats(await res.json());
        setError(null);
      } catch (err) {
        setError(String(err));
      }
    }
    void load();
  }, []);

  if (error) {
    return (
      <div className="rounded-md border border-border bg-muted/30 px-4 py-3 text-sm text-muted-foreground">
        Weekly stats unavailable — is the orchestrator running?
      </div>
    );
  }

  if (!stats?.enabled) {
    return null;
  }

  const days = stats.window_days ?? 7;
  const sources = Object.entries(stats.by_source ?? {})
    .map(([k, v]) => `${sourceLabel(k)} ${v}`)
    .join(" · ");

  return (
    <section className="rounded-lg border border-border bg-muted/20 p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium">Dogfood — last {days} days</h2>
        <span className="text-xs text-muted-foreground">
          Same view as <code className="text-[11px]">agentmetry stats --days {days}</code>
        </span>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <StatPill label="Events" value={String(stats.total_events ?? 0)} />
        <StatPill label="Sessions" value={String(stats.sessions ?? 0)} />
        <StatPill
          label="Detections"
          value={String(stats.detections ?? 0)}
          accent={(stats.detections ?? 0) > 0}
        />
        <StatPill label="Denied" value={String(stats.denied ?? 0)} accent={(stats.denied ?? 0) > 0} />
        <StatPill label="DLP hits" value={String(stats.dlp_matches ?? 0)} />
        <StatPill label="Policy blocks" value={String(stats.tool_policy_blocks ?? 0)} />
      </div>
      {sources ? (
        <p className="mt-3 text-xs text-muted-foreground">By source: {sources}</p>
      ) : null}
    </section>
  );
}
