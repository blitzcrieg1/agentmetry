"use client";

import { useEffect, useState } from "react";
import { useAgentStore } from "@/lib/store";
import { ORCHESTRATOR_URL } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { RunHistory } from "@/components/telemetry/run-history";
import { ServiceStatusPanel } from "@/components/telemetry/service-status";

interface HistoricalStats {
  backend: string;
  total_runs: number;
  success_rate: number;
  total_cost: number;
  avg_latency_ms: number;
  recent_runs?: Array<{
    skill: string;
    status: string;
    cost: number;
    latency_ms: number;
    created: string | null;
  }>;
}

export function TelemetryPanel() {
  const metrics = useAgentStore((s) => s.metrics);
  const memoryHeatmap = useAgentStore((s) => s.memoryHeatmap);
  const wsConnected = useAgentStore((s) => s.wsConnected);
  const [history, setHistory] = useState<HistoricalStats | null>(null);

  useEffect(() => {
    fetch(`${ORCHESTRATOR_URL}/api/v1/telemetry`)
      .then((r) => r.json())
      .then(setHistory)
      .catch(() => setHistory(null));
  }, [metrics.cost]);

  const topNotes = Object.entries(memoryHeatmap)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 5);

  return (
    <div className="flex flex-col gap-4 h-full">
      <ServiceStatusPanel />
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center justify-between">
            Session Telemetry
            <span
              className={`h-2 w-2 rounded-full ${wsConnected ? "bg-green-500" : "bg-red-500"}`}
            />
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <MetricRow label="Input Tokens" value={metrics.inputTokens.toLocaleString()} />
          <MetricRow label="Output Tokens" value={metrics.outputTokens.toLocaleString()} />
          <MetricRow label="Cost" value={`$${metrics.cost.toFixed(4)}`} />
          <MetricRow label="Latency" value={`${metrics.latencyMs}ms`} />

          <div>
            <div className="flex justify-between text-xs text-muted-foreground mb-1">
              <span>Context Window</span>
              <span>{metrics.contextUsagePercent}%</span>
            </div>
            <div className="h-2 rounded-full bg-muted overflow-hidden">
              <div
                className="h-full bg-primary transition-all duration-500 rounded-full"
                style={{ width: `${Math.min(metrics.contextUsagePercent, 100)}%` }}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {history && history.total_runs > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex justify-between">
              History
              <span className="text-xs font-normal text-muted-foreground">
                {history.backend}
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-xs">
            <MetricRow label="Total Runs" value={String(history.total_runs)} />
            <MetricRow
              label="Success Rate"
              value={`${(history.success_rate * 100).toFixed(0)}%`}
            />
            <MetricRow label="Total Cost" value={`$${history.total_cost.toFixed(4)}`} />
            {history.recent_runs?.slice(0, 3).map((run, i) => (
              <div key={i} className="flex justify-between text-muted-foreground font-mono">
                <span className="truncate">{run.skill}</span>
                <span className={run.status === "failed" ? "text-red-400" : "text-green-400"}>
                  {run.status}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <RunHistory />

      <Card className="flex-1">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Memory Heatmap</CardTitle>
        </CardHeader>
        <CardContent>
          {topNotes.length === 0 ? (
            <p className="text-xs text-muted-foreground">No notes accessed yet</p>
          ) : (
            <div className="space-y-2">
              {topNotes.map(([path, count]) => (
                <div key={path} className="flex items-center gap-2">
                  <div
                    className="h-3 rounded-sm bg-primary/60"
                    style={{ width: `${Math.min(count * 20, 100)}%`, minWidth: 8 }}
                  />
                  <span className="text-xs text-muted-foreground truncate">{path}</span>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function MetricRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono">{value}</span>
    </div>
  );
}
