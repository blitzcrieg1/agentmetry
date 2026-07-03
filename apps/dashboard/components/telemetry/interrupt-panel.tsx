"use client";

import { useEffect, useState } from "react";
import { useAgentStore } from "@/lib/store";
import { ORCHESTRATOR_URL } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface InterruptRow {
  interrupt_id: string;
  vector: string;
  skill_name: string;
  created_at?: string;
  payload?: Record<string, unknown>;
}

const VECTOR_STYLE: Record<string, { icon: string; color: string; label: string }> = {
  hitl_approval: { icon: "✋", color: "text-blue-400", label: "approval" },
  budget_defer: { icon: "⏸", color: "text-amber-400", label: "budget" },
  llm_degraded: { icon: "⚡", color: "text-red-400", label: "degraded" },
  tool_exec_approval: { icon: "🔧", color: "text-purple-400", label: "exec" },
};

function timeAgo(iso?: string): string {
  if (!iso) return "";
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86400)}d`;
}

export function InterruptPanel() {
  const runsRefreshKey = useAgentStore((s) => s.runsRefreshKey);
  const [rows, setRows] = useState<InterruptRow[]>([]);

  useEffect(() => {
    const fetchInterrupts = () => {
      fetch(`${ORCHESTRATOR_URL}/api/v1/skills/interrupts`)
        .then((r) => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.json();
        })
        .then((data) => setRows(data.interrupts || []))
        .catch(() => setRows([]));
    };
    fetchInterrupts();
    const interval = setInterval(fetchInterrupts, 60000);
    return () => clearInterval(interval);
  }, [runsRefreshKey]);

  if (rows.length === 0) return null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">
          Interrupts <span className="text-muted-foreground/60">· Gate</span>
          <span className="ml-2 text-xs font-normal text-muted-foreground">
            {rows.length} pending
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-1.5 text-xs">
        {rows.map((row) => {
          const style = VECTOR_STYLE[row.vector] || {
            icon: "•",
            color: "text-muted-foreground",
            label: row.vector,
          };
          const tool = row.payload?.tool as string | undefined;
          return (
            <div
              key={row.interrupt_id}
              className="flex items-center gap-2 font-mono"
              title={JSON.stringify(row.payload || {})}
            >
              <span>{style.icon}</span>
              <span className="truncate flex-1">
                {row.skill_name}
                {tool ? ` → ${tool}` : ""}
              </span>
              <span className={style.color}>{style.label}</span>
              <span className="text-muted-foreground whitespace-nowrap">
                {timeAgo(row.created_at)}
              </span>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
