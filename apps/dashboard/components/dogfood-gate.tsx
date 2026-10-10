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
      <div className="panel px-4 py-3 text-[13px] text-muted-foreground">
        Beta gate unavailable: {error}
      </div>
    );
  }
  if (!report) return null;

  if (!report.started) {
    return (
      <div className="panel px-4 py-3.5">
        <p className="eyebrow">Beta gate</p>
        <p className="mt-1.5 text-[14px] font-medium text-foreground">The dogfood clock has not started.</p>
        <p className="mt-1 text-[13px] text-muted-foreground">
          Start it with{" "}
          <code className="rounded-sm bg-muted px-1.5 py-0.5 font-mono text-[12px] text-foreground">agentmetry dogfood --start</code>.
          The gate is four consecutive green weeks.
        </p>
      </div>
    );
  }

  const remaining = weeksRemaining(report);
  const attention = needsAttention(report);

  return (
    <div className="panel">
      <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div className="flex items-center gap-2.5">
          <CalendarCheck className="h-4 w-4 text-subtle" />
          <span className="text-[14px] font-semibold">Beta gate</span>
          <span
            className={`rounded-sm px-1.5 py-0.5 font-mono text-[11px] font-medium uppercase ring-1 ring-inset ${
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
          className="rounded-sm p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          aria-label="Refresh beta gate"
        >
          <RefreshCw className="h-3 w-3" />
        </button>
      </div>

      <div className="px-4 py-2">
        <div className="hidden items-center gap-4 border-b border-border py-2 sm:flex">
          <span className="eyebrow w-16 shrink-0">Week</span>
          <span className="eyebrow w-48 shrink-0">Dates</span>
          <span className="eyebrow min-w-0 flex-1">Activity</span>
          <span className="eyebrow w-28 shrink-0 text-right">Verdict</span>
        </div>
        {report.weeks.map((week) => (
          <div key={week.index} className="border-b border-border py-2 last:border-b-0">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px]">
              <span className="w-16 shrink-0 font-medium">Week {week.index}</span>
              <span className="w-48 shrink-0 font-mono text-[12px] text-muted-foreground">
                {week.start} to {week.end}
              </span>
              <span className="min-w-0 flex-1 font-mono text-[12px] text-muted-foreground">
                {week.active_days} days, {week.events} events, {week.detections} detections
                {week.untriaged > 0 ? (
                  <span className="ml-2 text-caution">{week.untriaged} untriaged</span>
                ) : null}
              </span>
              <span className="w-28 shrink-0 text-right">
                <span
                  className={`inline-flex rounded-sm px-1.5 py-0.5 font-mono text-[11px] font-medium ring-1 ring-inset ${
                    VERDICT_CHIP[week.verdict]
                  }`}
                >
                  {week.verdict}
                </span>
              </span>
            </div>
            {week.reasons.map((reason) => (
              <p key={reason} className="mt-1 text-[12px] text-danger sm:pl-20">
                {reason}
              </p>
            ))}
          </div>
        ))}

        <p className="border-t border-border py-3 text-[12px] leading-relaxed text-muted-foreground">
          {report.passed
            ? "Four consecutive green weeks recorded."
            : `${remaining} more green week${remaining === 1 ? "" : "s"} needed. A week is green when the recorder ran on at least three days, the trail chain verifies, every critical or high detection was dispositioned, and nothing is stuck in the hook spool.`}
        </p>

        {!report.chain_ok ? (
          <p className="pb-3 text-[12px] text-danger">
            Trail chain does not verify: {report.chain_message}
          </p>
        ) : null}
        {report.spooled > 0 ? (
          <p className="pb-3 text-[12px] text-caution">
            {report.spooled} event(s) stuck in the hook spool; the orchestrator is not draining
            them.
          </p>
        ) : null}
      </div>
    </div>
  );
}
