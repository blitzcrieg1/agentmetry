import { describe, expect, it } from "vitest";

import { hitAgent, layoutAgents, project, rotate } from "@/lib/machine-scene";

describe("machine scene projection", () => {
  it("lays agents on a ring in the same order they were given", () => {
    const laid = layoutAgents([
      { name: "cursor", state: "covered" },
      { name: "claude", state: "covered" },
      { name: "codex", state: "uncovered" },
    ]);
    expect(laid.map((a) => a.name)).toEqual(["cursor", "claude", "codex"]);
    expect(laid[0].position.z).toBeCloseTo(-1.35, 5);
    expect(laid[2].position.y).toBeGreaterThan(laid[0].position.y);
  });

  it("puts an absent agent further from the host than a recorded one", () => {
    const laid = layoutAgents([
      { name: "cursor", state: "covered" },
      { name: "copilot", state: "absent" },
    ]);
    const radius = (p: { x: number; z: number }) => Math.hypot(p.x, p.z);
    expect(radius(laid[1].position)).toBeGreaterThan(radius(laid[0].position));
  });

  it("projects a closer point larger and nearer the centre", () => {
    const near = project({ x: 0, y: 0, z: -1 }, 400, 300);
    const far = project({ x: 0, y: 0, z: 1 }, 400, 300);
    expect(near.scale).toBeGreaterThan(far.scale);
    expect(near.depth).toBeLessThan(far.depth);
    expect(near.x).toBeCloseTo(200, 5);
  });

  it("rotates yaw around Y without moving Y", () => {
    const turned = rotate({ x: 1, y: 0.4, z: 0 }, Math.PI / 2, 0);
    expect(turned.x).toBeCloseTo(0, 5);
    expect(turned.z).toBeCloseTo(1, 5);
    expect(turned.y).toBeCloseTo(0.4, 5);
  });

  it("hits the agent whose projected cube is under the pointer", () => {
    const laid = layoutAgents([{ name: "cursor", state: "covered" }]);
    const drawn = project(rotate(laid[0].position, 0, 0), 400, 300);
    expect(hitAgent(laid, 0, 0, 400, 300, drawn.x, drawn.y)).toBe("cursor");
    expect(hitAgent(laid, 0, 0, 400, 300, 8, 8)).toBeNull();
  });
});
