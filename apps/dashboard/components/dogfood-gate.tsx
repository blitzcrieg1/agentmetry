"use client";

import { useCallback, useEffect, useState } from "react";
import { CalendarCheck, RefreshCw } from "lucide-react";
import {
  type DogfoodReport,
  VERDICT_CHIP,
  fetchDogfood,
  needsAttention,
  weeksRemaining,
} from "@/lib/dogfood";

export function DogfoodGate() {
  const [report, setReport] = useState<DogfoodReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setReport(await fetchDogfood());
      setError(null);
    } catch (err) {
      setError(String(err));
    }
  }, []);

  useEffect(() => {
    void load();
    // Weeks do not move quickly. Refresh on the same cadence as a coffee break.
    const timer = window.setInterval(() => void load(), 300_000);
    return () => window.clearInterval(timer);
  }, [load]);

  if (error && !report) {
    return (
      <div className="rounded-lg border border-border bg-card/40 p-3 text-xs text-muted-foreground">
        Beta gate unavailable: {error}
      </div>
    );
  }
  if (!report) return null;

  if (!report.started) {
    return (
      <div className="rounded-lg border border-border bg-card/40 p-3">
        <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Beta gate</p>
        <p className="mt-1 text-sm text-foreground">The dogfood clock has not started.</p>
        <p className="mt-1 text-xs text-muted-foreground">
          Start it with <code className="rounded bg-muted px-1">agentmetry dogfood --start</code>.
          Four consecutive green weeks.
        </p>
      </div>
    );
  }

  const remaining = weeksRemaining(report);
  const attention = needsAttention(report);

  return (
    <div className="rounded-lg border border-border bg-card/40">
      <div className="flex items-center justify-between gap-2 border-b border-border/60 px-3 py-2">
        <div className="flex items-center gap-2">
          <CalendarCheck className="h-4 w-4 text-muted-foreground" />
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Beta gate
          </span>
          <span
            className={`rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide ring-1 ring-inset ${
              report.passed
                ? VERDICT_CHIP.GREEN
                : attention
                  ? VERDICT_CHIP.RED
                  : VERDICT_CHIP["IN PROGRESS"]
            }`}
          >
            {report.passed
              ? "passed"
              : `${report.consecutive_green} of ${report.required} weeks`}
          </span>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          className="rounded border border-border p-1 text-muted-foreground transition hover:bg-muted hover:text-foreground"
          aria-label="Refresh beta gate"
        >
          <RefreshCw className="h-3 w-3" />
        </button>
      </div>

      <div className="space-y-1.5 p-3">
        {report.weeks.map((week) => (
          <div key={week.index}>
            <div className="flex items-center gap-2 text-xs">
              <span className="w-14 shrink-0 text-muted-foreground">Week {week.index}</span>
              <span className="w-40 shrink-0 font-mono text-[10px] text-muted-foreground">
                {week.start} to {week.end}
              </span>
              <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
                {week.active_days}d · {week.events} ev · {week.detections} det
              </span>
              {week.untriaged > 0 ? (
                <span className="shrink-0 font-mono text-[10px] text-amber-600 dark:text-amber-400">
                  {week.untriaged} untriaged
                </span>
              ) : null}
              <span
                className={`ml-auto shrink-0 rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide ring-1 ring-inset ${
                  VERDICT_CHIP[week.verdict]
                }`}
              >
                {week.verdict}
              </span>
            </div>
            {week.reasons.map((reason) => (
              <p key={reason} className="pl-16 text-[10px] text-red-600 dark:text-red-400">
                {reason}
              </p>
            ))}
          </div>
        ))}

        <p className="border-t border-border/50 pt-2 text-[10px] leading-relaxed text-muted-foreground">
          {report.passed
            ? "Four consecutive green weeks recorded."
            : `${remaining} more green week${remaining === 1 ? "" : "s"} needed. A week is green when the recorder ran on at least three days, the trail chain verifies, every critical or high detection was dispositioned, and nothing is stuck in the hook spool.`}
        </p>

        {!report.chain_ok ? (
          <p className="text-[10px] text-red-600 dark:text-red-400">
            Trail chain does not verify: {report.chain_message}
          </p>
        ) : null}
        {report.spooled > 0 ? (
          <p className="text-[10px] text-amber-600 dark:text-amber-400">
            {report.spooled} event(s) stuck in the hook spool; the orchestrator is not draining
            them.
          </p>
        ) : null}
      </div>
    </div>
  );
}
