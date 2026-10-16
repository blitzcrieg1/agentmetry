import { SEVERITY_DOT, type Severity } from "@/components/ui/kit";

const SEVERITY_RANK: Record<Severity, number> = {
  low: 1,
  medium: 2,
  high: 3,
  critical: 4,
};

export interface HistogramEvent {
  timestamp_utc?: string;
  action?: { outcome?: string };
  detection?: { severity?: string };
}

export interface HistogramBucket {
  iso: string;
  count: number;
  label: string;
  severity: Severity | null;
}

function asSeverity(value: string | undefined): Severity | null {
  if (value === "critical" || value === "high" || value === "medium" || value === "low") {
    return value;
  }
  return null;
}

/** Worst detection severity in one event. Ordinary tool calls have none. */
export function eventSeverity(event: HistogramEvent): Severity | null {
  const candidates = [asSeverity(event.action?.outcome), asSeverity(event.detection?.severity)];
  let best: Severity | null = null;
  for (const candidate of candidates) {
    if (!candidate) continue;
    if (!best || SEVERITY_RANK[candidate] > SEVERITY_RANK[best]) best = candidate;
  }
  return best;
}

function formatBucketLabel(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso.slice(11, 16);
  }
}

export function bucketEvents(events: HistogramEvent[], limit = 30): HistogramBucket[] {
  const counts = new Map<string, number>();
  const severity = new Map<string, Severity | null>();
  for (const ev of events) {
    if (!ev.timestamp_utc) continue;
    const d = new Date(ev.timestamp_utc);
    if (Number.isNaN(d.getTime())) continue;
    d.setSeconds(0, 0);
    const key = d.toISOString();
    counts.set(key, (counts.get(key) ?? 0) + 1);
    const next = eventSeverity(ev);
    const prev = severity.get(key) ?? null;
    if (next && (!prev || SEVERITY_RANK[next] > SEVERITY_RANK[prev])) {
      severity.set(key, next);
    } else if (!severity.has(key)) {
      severity.set(key, prev);
    }
  }
  if (counts.size === 0) return [];
  // Fill empty minutes so the x-axis is linear. Skipping them made a
  // three-hour gap between two bars look identical to one minute, which is
  // the opposite of what a rate chart is for.
  const keys = Array.from(counts.keys()).sort();
  const start = new Date(keys[0]).getTime();
  const end = new Date(keys[keys.length - 1]).getTime();
  const out: HistogramBucket[] = [];
  for (let t = end; t >= start && out.length < limit; t -= 60_000) {
    const iso = new Date(t).toISOString();
    out.unshift({
      iso,
      count: counts.get(iso) ?? 0,
      label: formatBucketLabel(iso),
      severity: severity.get(iso) ?? null,
    });
  }
  return out;
}

/** Severity colours come from the kit. A quiet minute stays gray. */
export function histogramBarClass(bucket: Pick<HistogramBucket, "count" | "severity">): string {
  if (bucket.count <= 0) return "bg-foreground/[0.07]";
  if (bucket.severity) return SEVERITY_DOT[bucket.severity];
  return "bg-foreground/35 group-hover:bg-signal";
}
