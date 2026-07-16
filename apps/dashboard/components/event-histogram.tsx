"use client";

import { useMemo } from "react";
import type { AuditEvent } from "@/components/flight-recorder-panel";

function formatBucketLabel(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso.slice(11, 16);
  }
}

export function EventHistogram({ events }: { events: AuditEvent[] }) {
  const buckets = useMemo(() => {
    const counts = new Map<string, number>();
    for (const ev of events) {
      if (!ev.timestamp_utc) continue;
      const d = new Date(ev.timestamp_utc);
      if (Number.isNaN(d.getTime())) continue;
      d.setSeconds(0, 0);
      const key = d.toISOString();
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    if (counts.size === 0) return [];
    // Fill empty minutes so the x-axis is linear. Skipping them made a
    // three-hour gap between two bars look identical to one minute, which is
    // the opposite of what a rate chart is for.
    const keys = Array.from(counts.keys()).sort();
    const start = new Date(keys[0]).getTime();
    const end = new Date(keys[keys.length - 1]).getTime();
    const out: { iso: string; count: number; label: string }[] = [];
    for (let t = end; t >= start && out.length < 30; t -= 60_000) {
      const iso = new Date(t).toISOString();
      out.unshift({ iso, count: counts.get(iso) ?? 0, label: formatBucketLabel(iso) });
    }
    return out;
  }, [events]);

  const max = useMemo(() => Math.max(1, ...buckets.map((b) => b.count)), [buckets]);

  if (buckets.length === 0) {
    return (
      <div className="flex h-16 items-center justify-center border-b border-border/60 px-4 text-[11px] text-muted-foreground">
        No events in the current window
      </div>
    );
  }

  return (
    <div className="border-b border-border/60 px-4 py-2">
      <div className="mb-1 flex items-center justify-between text-[10px] uppercase tracking-wider text-muted-foreground">
        <span>Event rate</span>
        <span className="font-mono normal-case tracking-normal">
          {events.length} events · {buckets.length} min buckets
        </span>
      </div>
      <div className="flex h-14 items-end gap-px">
        {buckets.map((b) => (
          <div key={b.iso} className="group relative flex min-w-0 flex-1 flex-col items-center justify-end">
            <div
              className={`w-full min-h-[2px] rounded-sm transition-colors ${
                b.count > 0 ? "bg-emerald-500/70 group-hover:bg-emerald-400" : "bg-emerald-500/15"
              }`}
              style={{ height: b.count > 0 ? `${Math.max(4, (b.count / max) * 100)}%` : "2px" }}
              title={`${b.label}: ${b.count}`}
            />
          </div>
        ))}
      </div>
      <div className="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground/80">
        <span>{buckets[0]?.label}</span>
        <span>{buckets[buckets.length - 1]?.label}</span>
      </div>
    </div>
  );
}
