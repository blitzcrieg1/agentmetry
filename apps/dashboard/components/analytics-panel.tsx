"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from "recharts";
import { Search } from "lucide-react";
import { ORCHESTRATOR_URL } from "@/lib/utils";
import { apiHeaders } from "@/lib/api";
import type { AuditEvent } from "./flight-recorder-panel";
import { detectionsFromEvents } from "./flight-recorder-panel";
import { eventSourceApp, sourceChartColor, sourceLabel } from "@/lib/audit-source";
import { EventHistogram } from "./event-histogram";
import { ProcessTree } from "./process-tree";
import { DogfoodStatsStrip } from "./dogfood-stats-strip";

const OUTCOME_COLORS: Record<string, string> = {
  success: "#34d399",
  pending: "#fbbf24",
  denied: "#f87171",
  error: "#f87171",
};

const CHART_TOOLTIP = {
  contentStyle: { backgroundColor: "hsl(var(--card))", border: "1px solid hsl(var(--border))", fontSize: "12px" },
  itemStyle: { color: "hsl(var(--foreground))" },
};

export function AnalyticsPanel() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedSession, setSelectedSession] = useState<string>("");

  useEffect(() => {
    async function fetchAll() {
      try {
        const res = await fetch(`${ORCHESTRATOR_URL}/api/v1/audit/tail?limit=500&scope=all`, {
          headers: apiHeaders(),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        setEvents(data.events || []);
        setError(null);
      } catch (err) {
        setError(String(err));
      } finally {
        setLoading(false);
      }
    }
    void fetchAll();
  }, []);

  const stats = useMemo(() => {
    let successCount = 0;
    let pendingCount = 0;
    let issueCount = 0;

    const sourceCounts: Record<string, number> = {};
    const mitreCounts: Record<string, number> = {};
    const sessions = new Set<string>();

    events.forEach((ev) => {
      const outcome = ev.action?.outcome || "success";
      const type = ev.action?.type ?? "";
      if (outcome === "success" && type !== "detection") successCount++;
      else if (outcome === "pending") pendingCount++;
      else issueCount++;

      const src = eventSourceApp(ev);
      sourceCounts[src] = (sourceCounts[src] || 0) + 1;

      const toolMitre = ev.tool?.mitre?.tactic;
      if (toolMitre) {
        mitreCounts[toolMitre] = (mitreCounts[toolMitre] || 0) + 1;
      }

      if (ev.correlation_id) sessions.add(ev.correlation_id);
    });

    const pieData = [
      { name: "Success", value: successCount },
      { name: "Pending", value: pendingCount },
      { name: "Issues", value: issueCount },
    ].filter((d) => d.value > 0);

    const sourceData = Object.entries(sourceCounts)
      .map(([name, value]) => ({ name: sourceLabel(name), key: name, value }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 5);

    const mitreData = Object.entries(mitreCounts)
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value);

    const detections = detectionsFromEvents(events);

    return {
      pieData,
      sourceData,
      mitreData,
      total: events.length,
      sessionCount: sessions.size,
      detectionCount: detections.length,
      successRate: events.length ? Math.round((successCount / events.length) * 100) : 0,
    };
  }, [events]);

  const uniqueSessions = useMemo(() => {
    const sessions = new Set<string>();
    events.forEach((e) => {
      if (e.correlation_id) sessions.add(e.correlation_id);
    });
    return Array.from(sessions);
  }, [events]);

  const treeEvents = useMemo(() => {
    if (!selectedSession) return [];
    return events.filter((e) => e.correlation_id === selectedSession);
  }, [events, selectedSession]);

  if (loading) {
    return (
      <div className="flex min-h-0 flex-1 flex-col items-center justify-center rounded-lg border border-border bg-card/20">
        <p className="text-sm text-muted-foreground">Loading analytics…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-1 rounded-lg border border-border bg-card/20">
        <p className="text-sm text-red-500 dark:text-red-400">Failed to load analytics</p>
        <p className="font-mono text-xs text-muted-foreground">{error}</p>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto rounded-lg border border-border bg-card/20">
      <div className="border-b border-border/60 px-4 py-3">
        <p className="text-sm font-semibold tracking-tight">Overview</p>
        <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
          Last {stats.total} events · {stats.sessionCount} sessions
        </p>
      </div>

      <div className="border-b border-border/60 px-4 py-3">
        <DogfoodStatsStrip />
      </div>

      <div className="grid grid-cols-2 gap-2 border-b border-border/60 px-4 py-3 sm:grid-cols-4">
        <StatCard label="Events" value={String(stats.total)} />
        <StatCard label="Sessions" value={String(stats.sessionCount)} />
        <StatCard label="Detections" value={String(stats.detectionCount)} accent={stats.detectionCount > 0} />
        <StatCard label="Success rate" value={`${stats.successRate}%`} />
      </div>

      <EventHistogram events={events} />

      <div className="grid grid-cols-1 gap-4 p-4 md:grid-cols-2">
        <ChartCard title="Action outcomes">
          <div className="h-48 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={stats.pieData}
                  cx="50%"
                  cy="50%"
                  innerRadius={50}
                  outerRadius={70}
                  paddingAngle={5}
                  dataKey="value"
                >
                  {stats.pieData.map((entry, index) => {
                    let color = OUTCOME_COLORS.success;
                    if (entry.name === "Pending") color = OUTCOME_COLORS.pending;
                    if (entry.name === "Issues") color = OUTCOME_COLORS.denied;
                    return <Cell key={`cell-${index}`} fill={color} />;
                  })}
                </Pie>
                <RechartsTooltip {...CHART_TOOLTIP} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </ChartCard>

        <ChartCard title="Activity by source">
          <div className="h-48 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={stats.sourceData} layout="vertical" margin={{ top: 0, right: 0, left: 20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" horizontal={false} />
                <XAxis type="number" className="text-muted-foreground" fontSize={10} />
                <YAxis dataKey="name" type="category" className="text-muted-foreground" fontSize={10} width={70} />
                <RechartsTooltip {...CHART_TOOLTIP} cursor={{ fill: "hsl(var(--muted))", opacity: 0.4 }} />
                <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                  {stats.sourceData.map((entry) => (
                    <Cell key={entry.key} fill={sourceChartColor(entry.key)} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </ChartCard>

        <ChartCard title="MITRE ATT&CK tactics" className="md:col-span-2">
          {stats.mitreData.length > 0 ? (
            <div className="h-48 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={stats.mitreData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border" vertical={false} />
                  <XAxis dataKey="name" className="text-muted-foreground" fontSize={10} />
                  <YAxis className="text-muted-foreground" fontSize={10} />
                  <RechartsTooltip {...CHART_TOOLTIP} cursor={{ fill: "hsl(var(--muted))", opacity: 0.4 }} />
                  <Bar dataKey="value" fill="#f87171" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="flex h-48 items-center justify-center">
              <p className="text-xs text-muted-foreground">No MITRE tactics logged in this window.</p>
            </div>
          )}
        </ChartCard>
      </div>

      <div className="mx-4 mb-4 rounded-lg border border-border/60 bg-card/40 p-4">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold">Session process tree</h3>
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
              Tool-call chain for one correlation id
            </p>
          </div>
          <div className="relative w-full max-w-xs">
            <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              type="text"
              list="session-options"
              className="w-full rounded-md border border-border bg-background py-1.5 pl-8 pr-2 text-sm text-foreground placeholder:text-muted-foreground focus:border-emerald-500/40 focus:outline-none"
              placeholder="Search session id…"
              value={selectedSession}
              onChange={(e) => setSelectedSession(e.target.value)}
            />
            <datalist id="session-options">
              {uniqueSessions.map((id) => (
                <option key={id} value={id} />
              ))}
            </datalist>
          </div>
        </div>
        <div className="h-[420px] w-full rounded-md border border-border/60 bg-background/50">
          <ProcessTree events={treeEvents} />
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="rounded-md border border-border/60 bg-background/50 px-3 py-2">
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className={`mt-0.5 font-mono text-lg font-semibold ${accent ? "text-red-400" : "text-foreground"}`}>
        {value}
      </p>
    </div>
  );
}

function ChartCard({
  title,
  children,
  className = "",
}: {
  title: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`rounded-lg border border-border/60 bg-card/40 p-4 ${className}`}>
      <h3 className="mb-4 text-xs font-semibold uppercase tracking-wider text-muted-foreground">{title}</h3>
      {children}
    </div>
  );
}
