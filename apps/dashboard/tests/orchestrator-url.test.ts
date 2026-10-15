/**
 * The static export used to bake http://localhost:8000 into every fetch.
 * `scripts/demo_dashboard.py` serves that export on 8010, so the page loaded
 * and the feed could not see the API unless the build had set
 * NEXT_PUBLIC_SAME_ORIGIN. A production build now uses relative URLs.
 */
import { describe, expect, it } from "vitest";

import { orchestratorHttpBase, orchestratorWsBase } from "@/lib/utils";

describe("orchestratorHttpBase", () => {
  it("keeps next dev on the orchestrator port", () => {
    expect(orchestratorHttpBase({ nodeEnv: "development", sameOriginFlag: false })).toBe(
      "http://localhost:8000",
    );
  });

  it("uses a relative URL for a production export, on the server and in the browser", () => {
    expect(
      orchestratorHttpBase({
        nodeEnv: "production",
        pageOrigin: "http://127.0.0.1:8010",
      }),
    ).toBe("");
  });

  it("lets an explicit URL win, including a split deploy", () => {
    expect(
      orchestratorHttpBase({
        configuredUrl: "https://recorder.internal:8000/",
        nodeEnv: "production",
      }),
    ).toBe("https://recorder.internal:8000");
  });

  it("follows the page when same-origin is forced outside production", () => {
    expect(
      orchestratorHttpBase({
        nodeEnv: "development",
        sameOriginFlag: true,
        pageOrigin: "http://127.0.0.1:8010",
      }),
    ).toBe("http://127.0.0.1:8010");
  });
});

describe("orchestratorWsBase", () => {
  it("follows the page host for a production export", () => {
    expect(
      orchestratorWsBase({
        nodeEnv: "production",
        pageProtocol: "http:",
        pageHost: "127.0.0.1:8010",
      }),
    ).toBe("ws://127.0.0.1:8010");
  });

  it("stays on :8000 during next dev", () => {
    expect(
      orchestratorWsBase({
        nodeEnv: "development",
        sameOriginFlag: false,
        pageProtocol: "http:",
        pageHost: "localhost:3000",
      }),
    ).toBe("ws://localhost:8000");
  });
});
