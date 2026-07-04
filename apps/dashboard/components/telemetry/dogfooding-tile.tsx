"use client";

import { useEffect, useState } from "react";
import { useAgentStore } from "@/lib/store";
import { ORCHESTRATOR_URL } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface SkillRow {
  skill: string;
  runs: number;
  successful: number;
}

interface SkillStats {
  window_days: number;
  by_skill: SkillRow[];
  distinct_skills_successful: number;
  go_no_go: { min_skills: number; dogfooding_met: boolean };
}

export function DogfoodingTile() {
  const runsRefreshKey = useAgentStore((s) => s.runsRefreshKey);
  const [stats, setStats] = useState<SkillStats | null>(null);

  useEffect(() => {
    const fetchStats = () => {
      fetch(`${ORCHESTRATOR_URL}/api/v1/runs/stats?window_days=7`)
        .then((r) => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.json();
        })
        .then(setStats)
        .catch(() => setStats(null));
    };
    fetchStats();
    const interval = setInterval(fetchStats, 60000);
    return () => clearInterval(interval);
  }, [runsRefreshKey]);

  if (!stats) return null;

  const { distinct_skills_successful: used, go_no_go } = stats;
  const met = go_no_go.dogfooding_met;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center justify-between">
          This week
          <span className={met ? "text-green-400" : "text-muted-foreground"}>
            {met ? "dogfooding ✓" : `${used}/${go_no_go.min_skills}`}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-1.5 text-xs">
        <div className={`text-sm font-mono ${met ? "text-green-400" : "text-amber-400"}`}>
          {used} skill{used === 1 ? "" : "s"} used
        </div>
        {stats.by_skill.slice(0, 5).map((row) => (
          <div key={row.skill} className="flex justify-between text-muted-foreground font-mono">
            <span className="truncate">{row.skill}</span>
            <span>
              {row.successful}✓{row.runs > row.successful ? ` / ${row.runs}` : ""}
            </span>
          </div>
        ))}
        {stats.by_skill.length === 0 && (
          <p className="text-muted-foreground">No runs in the last 7 days.</p>
        )}
      </CardContent>
    </Card>
  );
}
