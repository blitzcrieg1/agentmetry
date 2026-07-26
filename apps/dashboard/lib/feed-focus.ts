/**
 * Analytics → Event stream handoff.
 *
 * The dogfood stats strip shows counts; clicking a pill should open the feed
 * filtered to the events behind that count. This module is the shared contract
 * between the strip, the store, and the flight recorder.
 */

export type FeedFocusKind = "events" | "denied" | "dlp" | "policy" | "detections";

export type FeedFocus = {
  kind: FeedFocusKind;
};

/** Outcome chips the recorder should enable for a given focus. */
export function outcomeFiltersForFocus(kind: FeedFocusKind): {
  success: boolean;
  pending: boolean;
  issues: boolean;
} {
  if (kind === "events") {
    return { success: true, pending: true, issues: true };
  }
  // DLP / tool-policy in `log` mode keep outcome=success and still carry the
  // dlp / tool_policy block. Issues-only would hide the hits Analytics counted.
  if (kind === "dlp" || kind === "policy") {
    return { success: true, pending: false, issues: true };
  }
  return { success: false, pending: false, issues: true };
}

/** Maps UI focus to the /audit/tail `focus` query (null = no server filter). */
export function tailFocusParam(
  kind: FeedFocusKind,
): "denied" | "dlp" | "policy" | "detection" | null {
  if (kind === "events") return null;
  if (kind === "detections") return "detection";
  return kind;
}

/** Match Analytics `stats?days=7` window when drilling in from a count. */
export const FEED_FOCUS_SINCE_MINUTES = 7 * 24 * 60;

type FocusableEvent = {
  action?: { type?: string; outcome?: string; reason?: string };
  dlp?: unknown;
  tool_policy?: { blocked?: boolean; action?: string; rule_id?: string };
};

/** Whether one event belongs in the focused list. */
export function eventMatchesFocus(event: FocusableEvent, kind: FeedFocusKind): boolean {
  const action = event.action ?? {};
  const outcome = action.outcome ?? "";
  const reason = String(action.reason ?? "").toLowerCase();
  const type = action.type ?? "";

  switch (kind) {
    case "events":
      return true;
    case "denied":
      return outcome === "denied";
    case "dlp":
      return event.dlp != null || reason.startsWith("dlp:");
    case "policy": {
      const policy = event.tool_policy;
      if (policy && (policy.blocked || policy.action === "deny" || policy.action === "block")) {
        return true;
      }
      return reason.includes("tool_policy") || reason.includes("policy:");
    }
    case "detections":
      return type === "detection";
    default:
      return true;
  }
}

export const FEED_FOCUS_LABELS: Record<FeedFocusKind, string> = {
  events: "All events",
  denied: "Denied only",
  dlp: "DLP hits",
  policy: "Policy blocks",
  detections: "Detections",
};
