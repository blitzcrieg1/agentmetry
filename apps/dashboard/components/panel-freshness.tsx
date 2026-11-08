"use client";

import { useEffect, useState } from "react";

/** Fetch time is separate from the time of the newest recorded event. */
export function PanelFreshness({ at, scope, error }: { at: string | null; scope: string; error?: string | null }) {
  const [now, setNow] = useState(0);
  useEffect(() => {
    const tick = () => setNow(Date.now());
    tick();
    const timer = window.setInterval(tick, 30_000);
    return () => window.clearInterval(timer);
  }, []);
  const stale = Boolean(at && now - Date.parse(at) > 120_000);
  return (
    <div className="flex shrink-0 flex-wrap items-center justify-between gap-x-4 gap-y-1 text-[12px] text-muted-foreground" role="status">
      <span>{scope}</span>
      <span className={error || stale ? "text-caution" : ""} title={at ?? undefined}>
        {error ? at ? "Refresh failed. Showing last loaded data. " : "Data unavailable or partially loaded. " : stale ? "Snapshot may be stale. " : ""}
        {at ? `Loaded ${new Date(at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", timeZoneName: "short" })}` : "Not loaded yet"}
      </span>
    </div>
  );
}
