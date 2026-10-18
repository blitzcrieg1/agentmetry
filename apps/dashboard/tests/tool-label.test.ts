import { describe, expect, it } from "vitest";

import { toolColumnText, toolColumnTitle } from "@/lib/tool-label";

describe("toolColumnText", () => {
  it("keeps a real qualified name", () => {
    expect(toolColumnText({ tool: { qualified: "cursor.Read" } })).toBe("cursor.Read");
  });

  it("labels a decode failure instead of the unknown sentinel", () => {
    const event = {
      tool: { qualified: "cursor.unknown" },
      action: { reason: "stdin_decode_error" },
    };
    expect(toolColumnText(event)).toBe("unparsed");
    expect(toolColumnTitle(event)).toMatch(/did not parse/);
  });

  it("does not invent a name when the payload simply had none", () => {
    expect(
      toolColumnText({
        tool: { name: "unknown" },
        action: { reason: "decision:ask;hook:Notification" },
      }),
    ).toBeNull();
  });
});
