"use client";

import { useEffect, useState } from "react";
import { apiHeaders } from "@/lib/api";
import { ORCHESTRATOR_URL } from "@/lib/utils";
import { PanelFreshness } from "@/components/panel-freshness";

export type Destination = { seq: number; forwarded: number; dead_lettered: number; failing_for_seconds: number; last_error: string };

/** A refused event is a failed delivery, even while later batches succeed. */
export function forwardingStatus(destination: Destination): { text: string; attention: boolean } {
  const refused = destination.dead_lettered > 0
    ? `${destination.dead_lettered} ${destination.dead_lettered === 1 ? "event" : "events"} refused and dead-lettered`
    : "";
  if (destination.last_error || destination.failing_for_seconds) {
    const retrying = `Retrying · failing for ${Math.ceil(destination.failing_for_seconds)} s`;
    return { text: refused ? `${retrying} · ${refused}` : retrying, attention: true };
  }
  return refused ? { text: refused, attention: true } : { text: "No failure reported", attention: false };
}

export function ForwardingPanel() {
  const [destinations, setDestinations] = useState<Record<string, Destination>>({});
  const [at, setAt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const load = async () => {
      try {
        const response = await fetch(`${ORCHESTRATOR_URL}/api/v1/audit/status`, { headers: apiHeaders(), credentials: "include" });
        if (!response.ok) throw new Error("Forwarding status unavailable");
        const payload = await response.json();
        setDestinations(payload.forwarding ?? {});
        setAt(new Date().toISOString());
        setError(null);
      } catch { setError("Forwarding status unavailable"); }
    };
    void load();
    const timer = window.setInterval(load, 30_000);
    return () => window.clearInterval(timer);
  }, []);
  return (
    <section className="panel shrink-0" aria-label="SIEM forwarding">
      <header className="border-b border-border px-4 py-3"><h2 className="text-[14px] font-semibold">SIEM forwarding</h2><p className="mt-1 text-[12px] text-muted-foreground">Delivery progress reported by this recorder</p></header>
      <div className="space-y-3 p-4">
        <PanelFreshness at={at} scope="Active destination status" error={error} />
        {error ? <p role="alert" className="text-[13px] text-caution">Forwarding status unavailable. Delivery cannot be assessed.</p> : null}
        {!Object.keys(destinations).length && !error ? <p className="text-[13px] text-muted-foreground">No active forwarding destinations reported. This does not establish whether a destination is configured.</p> : null}
        {Object.entries(destinations).map(([name, destination]) => (
          <div key={name} className="rounded-md border border-border p-3">
            <div className="flex flex-wrap items-center justify-between gap-2"><span className="text-[13px] font-medium">{name}</span><span className={`text-[12px] ${forwardingStatus(destination).attention ? "text-caution" : "text-muted-foreground"}`}>{forwardingStatus(destination).text}</span></div>
            <dl className="mt-2 grid grid-cols-3 gap-3 text-[12px]">
              <div><dt className="text-muted-foreground">Last processed sequence</dt><dd className="font-mono">{destination.seq}</dd></div>
              <div><dt className="text-muted-foreground">Sent or refused</dt><dd className="font-mono">{destination.forwarded}</dd></div>
              <div><dt className="text-muted-foreground">Dead-lettered</dt><dd className="font-mono">{destination.dead_lettered}</dd></div>
            </dl>
          </div>
        ))}
        <p className="text-[12px] text-muted-foreground">The API does not expose a delivery timestamp or per-destination backlog. These are not inferred from event freshness.</p>
      </div>
    </section>
  );
}
