export interface ToolLabelEvent {
  tool?: { qualified?: string; name?: string };
  action?: { reason?: string };
}

const UNPARSED = "unparsed";
const UNPARSED_TITLE = "The hook payload did not parse, so the tool name was not recorded.";

function leafName(raw: string): string {
  const dot = raw.lastIndexOf(".");
  return dot >= 0 ? raw.slice(dot + 1) : raw;
}

/**
 * What the tool column should print.
 *
 * `unknown` is the mapper's sentinel for a missing name. On this trail that
 * is a stdin decode failure, not a tool called unknown. Showing the sentinel
 * made a broken payload look like a tool the operator should recognise.
 */
export function toolColumnText(event: ToolLabelEvent): string | null {
  const raw = (event.tool?.qualified || event.tool?.name || "").trim();
  const leaf = leafName(raw);
  if (!raw || leaf === "unknown" || raw === "unknown") {
    if ((event.action?.reason || "").includes("stdin_decode_error")) return UNPARSED;
    return null;
  }
  return raw;
}

export function toolColumnTitle(event: ToolLabelEvent): string {
  if (toolColumnText(event) === UNPARSED) return UNPARSED_TITLE;
  return event.tool?.qualified || event.tool?.name || "";
}
