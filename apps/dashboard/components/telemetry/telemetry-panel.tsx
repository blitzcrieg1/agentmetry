"use client";

import { useEffect, useState } from "react";
import { useAgentStore } from "@/lib/store";
import { ORCHESTRATOR_URL } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { RunHistory } from "@/components/telemetry/run-history";
import { ServiceStatusPanel } from "@/components/telemetry/service-status";
import { DogfoodingTile } from "@/components/telemetry/dogfooding-tile";
import { InterruptPanel } from "@/components/telemetry/interrupt-panel";
import { PendingApprovalsPanel } from "@/components/telemetry/pending-approvals-panel";
import { RecoveryPanel } from "@/components/telemetry/recovery-panel";

interface AuditHealth {
  llm_provider?: string;
  modes?: { llm?: string; rag?: string };
  vault?: { status?: string; notes?: number };
}

function OperatorSidebar() {
  const wsConnected = useAgentStore((s) => s.wsConnected);
  const [health, setHealth] = useState<AuditHealth | null>(null);

  useEffect(() => {
    fetch(`${ORCHESTRATOR_URL}/api/v1/health`)
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setHealth(null));
    const interval = setInterval(() => {
      fetch(`${ORCHESTRATOR_URL}/api/v1/health`)
        .then((r) => r.json())
        .then(setHealth)
        .catch(() => setHealth(null));
    }, 60000);
    return () => clearInterval(interval);
  }, []);

  const llm = health?.llm_provider || health?.modes?.llm || "—";

  return (
    <div className="flex flex-col gap-4 h-full">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center justify-between">
            Audit status
            <span
              className={`h-2 w-2 rounded-full ${wsConnected ? "bg-emerald-500" : "bg-red-500"}`}
              title={wsConnected ? "Live" : "Offline"}
            />
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-xs">
          <div className="flex justify-between">
            <span className="text-muted-foreground">Inference</span>
            <span className="font-mono capitalize">{llm}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Audit export</span>
            <span className="font-mono text-emerald-400">file · local</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Vault notes</span>
            <span className="font-mono">{health?.vault?.notes ?? "—"}</span>
          </div>
          <p className="pt-1 text-[10px] leading-relaxed text-muted-foreground">
            Pipe 2 (audit) stays on-box. Qdrant/Gemini down is normal on the mock profile.
          </p>
        </CardContent>
      </Card>

      <RunHistory />
    </div>
  );
}

function DevSidebar() {
  const metrics = useAgentStore((s) => s.metrics);
  const memoryHeatmap = useAgentStore((s) => s.memoryHeatmap);
  const wsConnected = useAgentStore((s) => s.wsConnected);

  const topNotes = Object.entries(memoryHeatmap)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 5);

  return (
    <div className="flex flex-col gap-4 h-full">
      <ServiceStatusPanel />
      <DogfoodingTile />
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center justify-between">
            Session
            <span className={`h-2 w-2 rounded-full ${wsConnected ? "bg-green-500" : "bg-red-500"}`} />
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-xs font-mono">
          <div className="flex justify-between">
            <span className="text-muted-foreground">Tokens in/out</span>
            <span>
              {metrics.inputTokens}/{metrics.outputTokens}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Cost</span>
            <span>${metrics.cost.toFixed(4)}</span>
          </div>
        </CardContent>
      </Card>
      <PendingApprovalsPanel />
      <InterruptPanel />
      <RecoveryPanel />
      <RunHistory />
      {topNotes.length > 0 ? (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Memory heatmap</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-xs text-muted-foreground">
            {topNotes.map(([path, count]) => (
              <div key={path} className="truncate">
                {path} ({count})
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

export function TelemetryPanel() {
  const devMode = useAgentStore((s) => s.devMode);
  return devMode ? <DevSidebar /> : <OperatorSidebar />;
}
