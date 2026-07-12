"use client";

import { useEffect, useState } from "react";
import { useAgentStore } from "@/lib/store";
import { ORCHESTRATOR_URL } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface RunRecord {
  thread_id: string | null;
  started?: string;
  updated?: string;
  skill?: string;
  status?: string;
  triggered_by?: string;
  cost?: number;
  latency_ms?: number;
  archive_path?: string;
  error?: string;
}

const STATUS_COLORS: Record<string, string> = {
  completed: "text-green-400",
  approved: "text-green-400",
  waiting_for_input: "text-amber-400",
  failed: "text-red-400",
  rejected: "text-red-400",
  terminated: "text-red-400",
  budget_exceeded: "text-amber-400",
};

function timeAgo(iso?: string): string {
  if (!iso) return "";
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return `${Math.floor(seconds)}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export function RunHistory() {
  const runsRefreshKey = useAgentStore((s) => s.runsRefreshKey);
  const [runs, setRuns] = useState<RunRecord[]>([]);

  useEffect(() => {
    const fetchRuns = () => {
      fetch(`${ORCHESTRATOR_URL}/api/v1/runs/?limit=15`)
        .then((r) => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.json();
        })
        .then((data) => setRuns(data.runs || []))
        .catch(() => setRuns([]));
    };
    fetchRuns();
    const interval = setInterval(fetchRuns, 60000);
    return () => clearInterval(interval);
  }, [runsRefreshKey]);

  if (runs.length === 0) return null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Recent runs</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1.5 text-xs">
        {runs.map((run, i) => (
          <div
            key={run.thread_id ?? `anon-${i}`}
            className="flex items-center gap-2 font-mono"
            title={run.error || run.archive_path || run.thread_id || ""}
          >
            <span>{run.triggered_by === "manual" || !run.triggered_by ? "👤" : "🤖"}</span>
            <span className="truncate flex-1">{run.skill || "—"}</span>
            <span className={STATUS_COLORS[run.status || ""] || "text-muted-foreground"}>
              {run.status || "?"}
            </span>
            <span className="text-muted-foreground whitespace-nowrap">
              {timeAgo(run.updated || run.started)}
            </span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
