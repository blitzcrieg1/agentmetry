"use client";

import { useEffect, useMemo, useState } from "react";
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
import { Activity } from "lucide-react";
import { ORCHESTRATOR_URL } from "@/lib/utils";
import { apiHeaders } from "@/lib/api";
import type { AuditEvent } from "./flight-recorder-panel";
import { ProcessTree } from "./process-tree";

const OUTCOME_COLORS: Record<string, string> = {
  success: "#34d399", // emerald-400
  pending: "#fbbf24", // amber-400
  denied: "#f87171",  // red-400
  error: "#f87171",
};

export function AnalyticsPanel() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedSession, setSelectedSession] = useState<string>("");

  useEffect(() => {
    async function fetchAll() {
      try {
        const res = await fetch(`${ORCHESTRATOR_URL}/api/v1/audit/tail?limit=500&scope=all`, {
          headers: apiHeaders(),
        });
        if (res.ok) {
          const data = await res.json();
          setEvents(data.events || []);
        }
      } catch (err) {
        console.error("Failed to load analytics data", err);
      } finally {
        setLoading(false);
      }
    }
    void fetchAll();
  }, []);

  const stats = useMemo(() => {
    let successCount = 0;
    let pendingCount = 0;
    let deniedCount = 0;

    const sourceCounts: Record<string, number> = {};
    const mitreCounts: Record<string, number> = {};

    events.forEach((ev) => {
      const outcome = ev.action?.outcome || "success";
      if (outcome === "success") successCount++;
      else if (outcome === "pending") pendingCount++;
      else deniedCount++;

      const src = ev.source?.app || ev.agent?.name || "unknown";
      sourceCounts[src] = (sourceCounts[src] || 0) + 1;

      // Type asserting since we just added mitre to the python schema
      const toolMitre = (ev.tool as any)?.mitre?.tactic;
      if (toolMitre) {
        mitreCounts[toolMitre] = (mitreCounts[toolMitre] || 0) + 1;
      }
    });

    const pieData = [
      { name: "Success", value: successCount },
      { name: "Pending", value: pendingCount },
      { name: "Denied/Error", value: deniedCount },
    ].filter(d => d.value > 0);

    const sourceData = Object.entries(sourceCounts)
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 5);

    const mitreData = Object.entries(mitreCounts)
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value);

    return { pieData, sourceData, mitreData, total: events.length };
  }, [events]);

  const uniqueSessions = useMemo(() => {
    const sessions = new Set<string>();
    events.forEach(e => {
      if (e.correlation_id) sessions.add(e.correlation_id);
    });
    return Array.from(sessions);
  }, [events]);

  const treeEvents = useMemo(() => {
    if (!selectedSession) return [];
    return events.filter(e => e.correlation_id === selectedSession);
  }, [events, selectedSession]);

  if (loading) {
    return (
      <div className="flex min-h-0 flex-1 flex-col items-center justify-center rounded-xl border border-slate-800/60 bg-slate-950/50">
        <p className="text-sm text-slate-500">Loading analytics…</p>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col rounded-xl border border-slate-800/60 bg-slate-950/50 overflow-y-auto">
      <div className="space-y-2 border-b border-slate-800/60 px-4 py-3">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-emerald-400" />
          <div>
            <p className="text-sm font-semibold text-slate-100">SIEM Analytics</p>
            <p className="text-[10px] text-slate-500">Last {stats.total} events</p>
          </div>
        </div>
      </div>

      <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Outcome Ratio */}
        <div className="rounded-lg border border-slate-800/60 bg-slate-900/30 p-4 flex flex-col items-center">
          <h3 className="text-xs font-semibold text-slate-300 mb-4">Action Outcomes</h3>
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
                    if (entry.name.includes("Denied")) color = OUTCOME_COLORS.denied;
                    return <Cell key={`cell-${index}`} fill={color} />;
                  })}
                </Pie>
                <RechartsTooltip 
                  contentStyle={{ backgroundColor: '#18181b', border: '1px solid #27272a', fontSize: '12px' }}
                  itemStyle={{ color: '#e4e4e7' }}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Top Talkers */}
        <div className="rounded-lg border border-slate-800/60 bg-slate-900/30 p-4">
          <h3 className="text-xs font-semibold text-slate-300 mb-4">Activity by Source</h3>
          <div className="h-48 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={stats.sourceData} layout="vertical" margin={{ top: 0, right: 0, left: 20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#27272a" horizontal={false} />
                <XAxis type="number" stroke="#52525b" fontSize={10} />
                <YAxis dataKey="name" type="category" stroke="#52525b" fontSize={10} width={70} />
                <RechartsTooltip 
                  contentStyle={{ backgroundColor: '#18181b', border: '1px solid #27272a', fontSize: '12px' }}
                  cursor={{ fill: '#27272a', opacity: 0.4 }}
                />
                <Bar dataKey="value" fill="#8b5cf6" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* MITRE ATT&CK */}
        <div className="col-span-1 md:col-span-2 rounded-lg border border-slate-800/60 bg-slate-900/30 p-4">
          <h3 className="text-xs font-semibold text-slate-300 mb-4">MITRE ATT&CK Tactics Detected</h3>
          {stats.mitreData.length > 0 ? (
            <div className="h-48 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={stats.mitreData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#27272a" vertical={false} />
                  <XAxis dataKey="name" stroke="#52525b" fontSize={10} />
                  <YAxis stroke="#52525b" fontSize={10} />
                  <RechartsTooltip 
                    contentStyle={{ backgroundColor: '#18181b', border: '1px solid #27272a', fontSize: '12px' }}
                    cursor={{ fill: '#27272a', opacity: 0.4 }}
                  />
                  <Bar dataKey="value" fill="#ec4899" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="h-48 flex items-center justify-center">
              <p className="text-xs text-slate-500">No MITRE tactics logged in this window.</p>
            </div>
          )}
        </div>
      </div>

      {/* PROCESS TREE DIAGRAM */}
      <div className="mt-6 rounded-lg border border-slate-800/60 bg-slate-900/30 p-4">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-slate-300">Session Process Tree</h3>
          <div className="relative w-64">
            <input 
              type="text"
              list="session-options"
              className="w-full bg-slate-800 border border-slate-700 text-slate-200 text-sm rounded-md focus:ring-emerald-500 focus:border-emerald-500 block p-2 pr-8"
              placeholder="Search Session ID..."
              value={selectedSession}
              onChange={(e) => setSelectedSession(e.target.value)}
            />
            <datalist id="session-options">
              {uniqueSessions.map(id => (
                <option key={id} value={id} />
              ))}
            </datalist>
          </div>
        </div>
        <div className="h-[500px] w-full">
          <ProcessTree events={treeEvents} />
        </div>
      </div>
    </div>
  );
}
