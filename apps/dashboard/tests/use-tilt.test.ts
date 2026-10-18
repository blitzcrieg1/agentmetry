import { describe, expect, it } from "vitest";

import { MAX_TILT, tiltFor } from "@/lib/use-tilt";

describe("tile tilt", () => {
  it("is flat at the centre", () => {
    expect(tiltFor(100, 50, 200, 100)).toEqual({ rx: 0, ry: 0 });
  });

  it("leans toward the pointer, at most MAX_TILT degrees at a corner", () => {
    expect(tiltFor(200, 0, 200, 100)).toEqual({ rx: MAX_TILT, ry: MAX_TILT });
    expect(tiltFor(0, 100, 200, 100)).toEqual({ rx: -MAX_TILT, ry: -MAX_TILT });
  });

  it("clamps a pointer outside the box and ignores an empty box", () => {
    expect(tiltFor(900, -50, 200, 100)).toEqual({ rx: MAX_TILT, ry: MAX_TILT });
    expect(tiltFor(10, 10, 0, 0)).toEqual({ rx: 0, ry: 0 });
  });
});
