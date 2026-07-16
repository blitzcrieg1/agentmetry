import type { AuditEvent } from "@/components/flight-recorder-panel";

// Trails written before the Agentmetry rename carry the legacy first-party
// name. Normalize on read so old events keep rendering under one label —
// this must happen everywhere a source is displayed, or the dead codename
// leaks into charts (which is exactly how the third copy of this logic
// drifted before it was consolidated here).
const LEGACY_SOURCE_APPS = new Set(["blackbox"]);

export const normalizeSourceApp = (name: string): string =>
  LEGACY_SOURCE_APPS.has(name) ? "agentmetry" : name;

export function eventSourceApp(event: AuditEvent): string {
  if (event.source?.app) return normalizeSourceApp(event.source.app);
  const agent = event.agent?.name ? normalizeSourceApp(event.agent.name) : "";
  if (agent && agent !== "agentmetry") return agent;
  return "agentmetry";
}
