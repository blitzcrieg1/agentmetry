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
import { DogfoodGate } from "./dogfood-gate";

// Recharts writes these as SVG attributes, where var() does not resolve, so
// they go through style instead. Same tokens as everywhere else.
const OUTCOME_FILL: Record<string, string> = {
  Success: "hsl(var(--secure))",
  Pending: "hsl(var(--caution))",
  Issues: "hsl(var(--danger))",
};

const CHART_TOOLTIP = {
  contentStyle: {
    backgroundColor: "hsl(var(--popover))",
    border: "1px solid hsl(var(--border))",
    borderRadius: "3px",
    fontSize: "12px",
  },
  itemStyle: { color: "hsl(var(--foreground))" },
  labelStyle: { color: "hsl(var(--muted-foreground))" },
};

const AXIS_TICK = { fill: "hsl(var(--muted-foreground))", fontSize: 11 };

type WeekStats = {
  enabled: boolean;
  window_days?: number;
  total_events?: number;
  sessions?: number;
  detections?: number;
  denied?: number;
  dlp_matches?: number;
  tool_policy_blocks?: number;
  by_source?: Record<string, number>;
};

export function AnalyticsPanel() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [week, setWeek] = useState<WeekStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedSession, setSelectedSession] = useState<string>("");

  useEffect(() => {
    async function fetchAll() {
      try {
        const [tailRes, statsRes] = await Promise.all([
          fetch(`${ORCHESTRATOR_URL}/api/v1/audit/tail?limit=500&scope=all`, {
            headers: apiHeaders(),
            credentials: "include",
          }),
          fetch(`${ORCHESTRATOR_URL}/api/v1/audit/stats?days=7`, {
            headers: apiHeaders(),
            credentials: "include",
          }),
        ]);
        if (!tailRes.ok) throw new Error(`tail HTTP ${tailRes.status}`);
        if (!statsRes.ok) throw new Error(`stats HTTP ${statsRes.status}`);
        const tailData = await tailRes.json();
        const statsData = (await statsRes.json()) as WeekStats;
        setEvents(tailData.events || []);
        setWeek(statsData);
        setError(null);
      } catch (err) {
        setError(String(err));
      } finally {
        setLoading(false);
      }
    }
    void fetchAll();
  }, []);

  const chartStats = useMemo(() => {
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

    const weekSourceData = Object.entries(week?.by_source ?? {})
      .map(([name, value]) => ({ name: sourceLabel(name), key: name, value }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 5);

    const mitreData = Object.entries(mitreCounts)
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value);

    const detections = detectionsFromEvents(events);

    return {
      pieData,
      sourceData: weekSourceData.length > 0 ? weekSourceData : sourceData,
      mitreData,
      sampleTotal: events.length,
      sampleSessions: sessions.size,
      sampleDetections: detections.length,
      successRate: events.length ? Math.round((successCount / events.length) * 100) : 0,
    };
  }, [events, week]);

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
      <div className="panel flex min-h-0 flex-1 items-center justify-center">
        <p className="text-[13px] text-muted-foreground">Loading analytics…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="panel flex min-h-0 flex-1 flex-col items-center justify-center gap-1">
        <p className="text-[13px] text-danger">Failed to load analytics</p>
        <p className="font-mono text-[12px] text-muted-foreground">{error}</p>
      </div>
    );
  }

  const days = week?.window_days ?? 7;

  return (
    <div className="-mx-1 flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-1 pb-2">
      <DogfoodStatsStrip />
      <DogfoodGate />

      <div className="flex items-baseline justify-between gap-2 pt-2">
        <h2 className="text-[15px] font-semibold">Recent activity</h2>
        <p className="text-[12px] text-subtle">
          Charts sample the newest {chartStats.sampleTotal} events, not the full week
        </p>
      </div>

      <EventHistogram events={events} />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <ChartCard title="Action outcomes" note="sample">
          <div className="flex h-48 w-full items-center gap-6">
            <div className="h-full min-w-0 flex-1">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={chartStats.pieData}
                    cx="50%"
                    cy="50%"
                    innerRadius={52}
                    outerRadius={72}
                    paddingAngle={2}
                    stroke="none"
                    dataKey="value"
                  >
                    {chartStats.pieData.map((entry, index) => (
                      <Cell key={`cell-${index}`} style={{ fill: OUTCOME_FILL[entry.name] ?? OUTCOME_FILL.Success }} />
                    ))}
                  </Pie>
                  <RechartsTooltip {...CHART_TOOLTIP} />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <ul className="w-32 shrink-0 space-y-2 text-[12px]">
              {chartStats.pieData.map((d) => (
                <li key={d.name} className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-2 text-muted-foreground">
                    <span className="h-2 w-2 rounded-full" style={{ background: OUTCOME_FILL[d.name] }} />
                    {d.name}
                  </span>
                  <span className="font-mono text-foreground">{d.value}</span>
                </li>
              ))}
            </ul>
          </div>
        </ChartCard>

        <ChartCard title="Activity by source" note={`${days} days`}>
          <div className="h-48 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartStats.sourceData} layout="vertical" margin={{ top: 0, right: 8, left: 8, bottom: 0 }}>
                <CartesianGrid strokeDasharray="2 4" stroke="hsl(var(--border))" horizontal={false} />
                <XAxis type="number" tick={AXIS_TICK} axisLine={false} tickLine={false} />
                <YAxis dataKey="name" type="category" tick={AXIS_TICK} axisLine={false} tickLine={false} width={80} />
                <RechartsTooltip {...CHART_TOOLTIP} cursor={{ fill: "hsl(var(--muted))", opacity: 0.6 }} />
                <Bar dataKey="value" radius={[0, 2, 2, 0]} barSize={14}>
                  {chartStats.sourceData.map((entry) => (
                    <Cell key={entry.key} fill={sourceChartColor(entry.key)} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </ChartCard>

        <ChartCard title="MITRE ATT&CK tactics" note="sample" className="md:col-span-2">
          {chartStats.mitreData.length > 0 ? (
            <div className="h-48 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartStats.mitreData} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="2 4" stroke="hsl(var(--border))" vertical={false} />
                  <XAxis dataKey="name" tick={AXIS_TICK} axisLine={false} tickLine={false} />
                  <YAxis tick={AXIS_TICK} axisLine={false} tickLine={false} allowDecimals={false} />
                  <RechartsTooltip {...CHART_TOOLTIP} cursor={{ fill: "hsl(var(--muted))", opacity: 0.6 }} />
                  <Bar dataKey="value" radius={[2, 2, 0, 0]} barSize={28} style={{ fill: "hsl(var(--signal))" }} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="flex h-48 items-center justify-center">
              <p className="text-[12px] text-subtle">No MITRE tactics logged in this sample.</p>
            </div>
          )}
        </ChartCard>
      </div>

      <section className="panel">
        <div className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3">
          <Search className="h-4 w-4 text-subtle" />
          <div className="min-w-0">
            <h3 className="text-[14px] font-semibold">Session timeline</h3>
            <p className="text-[12px] text-muted-foreground">Every call in one session, in order</p>
          </div>
          <select
            aria-label="Session"
            className="control ml-auto max-w-full font-mono text-[12px]"
            value={selectedSession}
            onChange={(e) => setSelectedSession(e.target.value)}
          >
            <option value="">Select a session…</option>
            {uniqueSessions.map((id) => (
              <option key={id} value={id}>
                {id.length > 36 ? `${id.slice(0, 20)}…${id.slice(-8)}` : id}
              </option>
            ))}
          </select>
        </div>
        <div className="p-4">
          {selectedSession ? (
            <ProcessTree events={treeEvents} />
          ) : (
            <p className="py-8 text-center text-[12px] text-subtle">
              Pick a session to lay out its calls on a timeline.
            </p>
          )}
        </div>
      </section>
    </div>
  );
}

function ChartCard({
  title,
  note,
  children,
  className = "",
}: {
  title: string;
  note?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`panel p-4 ${className}`}>
      <div className="mb-3 flex items-baseline justify-between gap-2">
        <p className="text-[13px] font-medium">{title}</p>
        {note ? <p className="text-[11px] text-subtle">{note}</p> : null}
      </div>
      {children}
    </div>
  );
}
