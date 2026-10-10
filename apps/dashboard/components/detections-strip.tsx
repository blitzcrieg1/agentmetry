"use client";

import { Pin, ShieldCheck } from "lucide-react";
import type { Detection } from "@/components/flight-recorder-panel";
import { SEVERITY_DOT } from "@/components/ui/kit";

const SEV_ORDER: Record<string, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

const SEV_CHIP: Record<string, string> = {
  critical: "border-danger/35 bg-danger/[0.07]",
  high: "border-signal/35 bg-signal/[0.06]",
  medium: "border-caution/35 bg-caution/[0.06]",
  low: "border-border bg-card",
};

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
      <div className="flex items-center gap-2 text-[12px] text-subtle">
        <ShieldCheck className="h-3.5 w-3.5 shrink-0" />
        No correlated detections in this view
      </div>
    );
  }

  return (
    <div className="flex min-w-0 items-center gap-2">
      <span className="shrink-0 text-[12px] text-subtle">
        Detections in view <span className="font-mono text-foreground">{sorted.length}</span>
      </span>
      <div className="flex min-w-0 flex-1 gap-2 overflow-x-auto pb-0.5">
        {sorted.map((d) => {
          const active = activeRuleId === d.rule_id;
          return (
            <div
              key={`${d.rule_id}-${d.correlation_id}`}
              className={`flex shrink-0 items-stretch overflow-hidden rounded-sm border transition-colors ${SEV_CHIP[d.severity] ?? SEV_CHIP.low} ${
                active ? "ring-1 ring-signal" : "hover:border-foreground/25"
              }`}
            >
              <button
                type="button"
                aria-pressed={active}
                onClick={() => onSelect?.(active ? null : d.rule_id)}
                className="flex min-w-0 items-center gap-2 px-2.5 py-1 text-left"
                title={`${d.severity}: filter events for this rule`}
              >
                <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${SEVERITY_DOT[d.severity] ?? SEVERITY_DOT.low}`} />
                <span className="max-w-[16rem] truncate text-[12px] font-medium text-foreground">{d.title}</span>
                {d.technique_ids.length > 0 ? (
                  <span className="hidden font-mono text-[11px] text-subtle xl:inline">
                    {d.technique_ids.join(" → ")}
                  </span>
                ) : null}
              </button>
              {d.correlation_id && onOpenSession ? (
                <button
                  type="button"
                  onClick={() => onOpenSession(d.correlation_id)}
                  className="flex items-center border-l border-border px-2 text-subtle transition-colors hover:bg-muted hover:text-foreground"
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
      {activeRuleId && onSelect ? (
        <button
          type="button"
          onClick={() => onSelect(null)}
          className="shrink-0 text-[12px] font-medium text-signal hover:underline"
        >
          Clear filter
        </button>
      ) : null}
    </div>
  );
}
