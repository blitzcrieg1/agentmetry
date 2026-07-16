"use client";

import { Pin, ShieldAlert } from "lucide-react";
import type { Detection } from "@/components/flight-recorder-panel";

const SEV_ORDER: Record<string, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

function sevClass(severity: string): string {
  if (severity === "critical" || severity === "high") {
    return "border-red-500/40 bg-red-100 text-red-900 hover:bg-red-200 dark:bg-red-950/40 dark:text-red-100 dark:hover:bg-red-950/60";
  }
  if (severity === "medium") {
    return "border-amber-500/40 bg-amber-100 text-amber-900 hover:bg-amber-200 dark:bg-amber-950/30 dark:text-amber-100 dark:hover:bg-amber-950/50";
  }
  return "border-border bg-muted/40 text-muted-foreground hover:bg-muted/60";
}

export function DetectionsStrip({
  detections,
  activeRuleId,
  onSelect,
  onOpenSession,
}: {
  detections: Detection[];
  activeRuleId?: string | null;
  onSelect?: (ruleId: string | null) => void;
  onOpenSession?: (correlationId: string) => void;
}) {
  const sorted = [...detections].sort(
    (a, b) => (SEV_ORDER[a.severity] ?? 9) - (SEV_ORDER[b.severity] ?? 9),
  );

  if (sorted.length === 0) {
    return (
      <div className="flex items-center gap-2 border-b border-border/60 px-4 py-2 text-[11px] text-muted-foreground">
        <ShieldAlert className="h-3.5 w-3.5 shrink-0 opacity-50" />
        No correlated detections in this view
      </div>
    );
  }

  return (
    <div className="border-b border-border/60 px-4 py-2">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
          <ShieldAlert className="h-3.5 w-3.5 text-red-500 dark:text-red-400" />
          Detections
          <span className="rounded bg-red-500/15 px-1.5 py-0.5 font-mono text-red-700 dark:bg-red-500/20 dark:text-red-300">{sorted.length}</span>
        </div>
        {activeRuleId && onSelect ? (
          <button
            type="button"
            onClick={() => onSelect(null)}
            className="text-[10px] text-emerald-700 hover:text-emerald-600 dark:text-emerald-400 dark:hover:text-emerald-300"
          >
            Clear filter
          </button>
        ) : null}
      </div>
      <div className="flex gap-2 overflow-x-auto pb-0.5">
        {sorted.map((d) => {
          const active = activeRuleId === d.rule_id;
          return (
            <div
              key={`${d.rule_id}-${d.correlation_id}`}
              className={`flex shrink-0 items-stretch overflow-hidden rounded border transition ${sevClass(d.severity)} ${
                active ? "ring-1 ring-emerald-500/50" : ""
              }`}
            >
              <button
                type="button"
                onClick={() => onSelect?.(active ? null : d.rule_id)}
                className="flex min-w-0 items-center gap-2 px-2.5 py-1.5 text-left"
                title="Filter events for this rule"
              >
                <span className="rounded bg-black/10 px-1 py-0.5 text-[9px] font-bold uppercase tracking-wide dark:bg-black/30">
                  {d.severity}
                </span>
                <span className="max-w-[12rem] truncate text-xs font-medium">{d.title}</span>
                {d.technique_ids.length > 0 ? (
                  <span className="hidden font-mono text-[10px] opacity-70 sm:inline">
                    {d.technique_ids.join(" → ")}
                  </span>
                ) : null}
              </button>
              {d.correlation_id && onOpenSession ? (
                <button
                  type="button"
                  onClick={() => onOpenSession(d.correlation_id)}
                  className="flex items-center border-l border-black/10 px-2 text-inherit opacity-70 transition hover:bg-black/10 hover:opacity-100 dark:border-black/20 dark:hover:bg-black/20"
                  title="Pin full session"
                  aria-label={`Pin session ${d.correlation_id}`}
                >
                  <Pin className="h-3 w-3" />
                </button>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
