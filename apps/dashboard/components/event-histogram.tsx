"use client";

import { useMemo } from "react";
import type { AuditEvent } from "@/components/flight-recorder-panel";
import { bucketEvents, histogramBarClass } from "@/lib/event-histogram";

export function EventHistogram({ events }: { events: AuditEvent[] }) {
  const buckets = useMemo(() => bucketEvents(events), [events]);
  const max = useMemo(() => Math.max(1, ...buckets.map((b) => b.count)), [buckets]);

  if (buckets.length === 0) {
    return (
      <div className="panel flex h-[5.5rem] items-center justify-center px-4 text-[12px] text-subtle">
        No events in the current window
      </div>
    );
  }

  return (
    <div className="panel px-4 pb-2.5 pt-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-[12px] font-medium text-muted-foreground">Event rate</span>
        <span className="font-mono text-[11px] text-subtle">
          {events.length} events, {buckets.length} one-minute buckets
        </span>
      </div>
      <div className="flex h-11 items-end gap-[3px]">
        {buckets.map((b) => (
          <div key={b.iso} className="group relative flex h-full min-w-0 flex-1 flex-col items-center justify-end">
            <div
              className={`w-full rounded-[1px] transition-colors ${histogramBarClass(b)}`}
              style={{ height: b.count > 0 ? `${Math.max(6, (b.count / max) * 100)}%` : "2px" }}
              title={
                b.severity
                  ? `${b.label}: ${b.count}, ${b.severity}`
                  : `${b.label}: ${b.count}`
              }
            />
          </div>
        ))}
      </div>
      <div className="mt-1.5 flex justify-between font-mono text-[10px] text-subtle">
        <span>{buckets[0]?.label}</span>
        <span>{buckets[buckets.length - 1]?.label}</span>
      </div>
    </div>
  );
}
