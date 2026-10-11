"use client";

import { useEffect, useState } from "react";
import { ORCHESTRATOR_URL } from "@/lib/utils";
import { apiHeaders } from "@/lib/api";
import { sourceLabel } from "@/lib/audit-source";
import { useAgentStore } from "@/lib/store";
import type { FeedFocusKind } from "@/lib/feed-focus";

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

function StatPill({
  label,
  value,
  accent,
  onClick,
  title,
}: {
  label: string;
  value: string;
  accent?: boolean;
  onClick?: () => void;
  title?: string;
}) {
  const className = `panel px-4 py-3 text-left transition-colors ${
    onClick
      ? "cursor-pointer hover:border-foreground/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal/30"
      : ""
  }`;

  const body = (
    <>
      <div className="text-[12px] font-medium text-muted-foreground">{label}</div>
      <div className={`mt-1 text-[24px] font-semibold leading-tight tabular-nums ${accent ? "text-caution" : ""}`}>
        {value}
      </div>
    </>
  );

  if (!onClick) {
    return <div className={className}>{body}</div>;
  }

  return (
    <button type="button" className={className} onClick={onClick} title={title}>
      {body}
    </button>
  );
}

export function DogfoodStatsStrip() {
  const requestFeedFocus = useAgentStore((s) => s.requestFeedFocus);
  const [stats, setStats] = useState<AuditStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const res = await fetch(`${ORCHESTRATOR_URL}/api/v1/audit/stats?days=7`, {
          headers: apiHeaders(),
          credentials: "include",
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        setStats(await res.json());
        setError(null);
      } catch (err) {
        setError(String(err));
      }
    }
    void load();
    const timer = window.setInterval(() => void load(), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  if (error) {
    return (
      <div className="panel px-4 py-3 text-[13px] text-muted-foreground">
        Weekly stats unavailable. Is the orchestrator running?
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

  const open = (kind: FeedFocusKind) => () => requestFeedFocus(kind);

  return (
    <section>
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-[15px] font-semibold">Last {days} days</h2>
        <span className="text-[12px] text-subtle">
          Click a count to open the matching events. Same numbers as{" "}
          <code className="font-mono text-[11px] text-muted-foreground">agentmetry stats --days {days}</code>
        </span>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
        <StatPill
          label="Events"
          value={String(stats.total_events ?? 0)}
          onClick={open("events")}
          title="Open Event stream (all outcomes)"
        />
        <StatPill label="Sessions" value={String(stats.sessions ?? 0)} />
        <StatPill
          label="Detections"
          value={String(stats.detections ?? 0)}
          accent={(stats.detections ?? 0) > 0}
          onClick={open("detections")}
          title="Open Detections triage"
        />
        <StatPill
          label="Denied"
          value={String(stats.denied ?? 0)}
          accent={(stats.denied ?? 0) > 0}
          onClick={open("denied")}
          title="Show denied tool calls in Event stream"
        />
        <StatPill
          label="DLP hits"
          value={String(stats.dlp_matches ?? 0)}
          onClick={open("dlp")}
          title="Show DLP matches in Event stream"
        />
        <StatPill
          label="Policy blocks"
          value={String(stats.tool_policy_blocks ?? 0)}
          onClick={open("policy")}
          title="Show tool-policy blocks in Event stream"
        />
      </div>
      {sources ? (
        <p className="mt-2.5 text-[12px] text-muted-foreground">By source: {sources}</p>
      ) : null}
    </section>
  );
}
