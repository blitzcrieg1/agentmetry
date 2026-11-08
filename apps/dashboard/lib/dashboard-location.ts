export const DASHBOARD_PAGES = ["overview", "machine", "recorder", "detections", "identity", "analytics"] as const;
export type DashboardPage = typeof DASHBOARD_PAGES[number];
export type DashboardLocation = { page: DashboardPage; session?: string; rule?: string; view?: string };

/** The detection a location names, when it names one. */
export function detectionFromLocation(location: DashboardLocation): { correlationId: string; ruleId: string } | undefined {
  return location.session && location.rule ? { correlationId: location.session, ruleId: location.rule } : undefined;
}

export function parseDashboardLocation(hash: string): DashboardLocation {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const page = params.get("page") as DashboardPage;
  return { page: DASHBOARD_PAGES.includes(page) ? page : "overview", session: params.get("session") || undefined, rule: params.get("rule") || undefined, view: params.get("view") || undefined };
}

export function writeDashboardLocation(location: DashboardLocation, replace = false) {
  const params = new URLSearchParams({ page: location.page });
  if (location.session) params.set("session", location.session);
  if (location.rule) params.set("rule", location.rule);
  if (location.view) params.set("view", location.view);
  const hash = `#${params}`;
  if (window.location.hash === hash) return;
  if (replace) window.history.replaceState(null, "", hash);
  else window.history.pushState(null, "", hash);
}
