"use client";

import { useAgentStore } from "@/lib/store";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function TelemetryPanel() {
  const metrics = useAgentStore((s) => s.metrics);
  const memoryHeatmap = useAgentStore((s) => s.memoryHeatmap);
  const wsConnected = useAgentStore((s) => s.wsConnected);

  const topNotes = Object.entries(memoryHeatmap)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 5);

  return (
    <div className="flex flex-col gap-4 h-full">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center justify-between">
            Telemetry
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
