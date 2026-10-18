import { afterEach, describe, expect, it, vi } from "vitest";

import { checkSession, signOut } from "@/lib/session";

afterEach(() => {
  vi.unstubAllGlobals();
});

const respond = (status: number) => vi.fn(async () => new Response("{}", { status }));

describe("session", () => {
  it("reads a 401 as signed out, not as an outage", async () => {
    vi.stubGlobal("fetch", respond(401));
    expect(await checkSession()).toBe("signed_out");
  });

  it("reads a 200 as signed in, and anything else as unreachable", async () => {
    vi.stubGlobal("fetch", respond(200));
    expect(await checkSession()).toBe("signed_in");
    vi.stubGlobal("fetch", respond(500));
    expect(await checkSession()).toBe("unreachable");
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("connection refused"))));
    expect(await checkSession()).toBe("unreachable");
  });

  it("signs out with a POST that carries the cookie and the CSRF header", async () => {
    const fetchMock = respond(200);
    vi.stubGlobal("fetch", fetchMock);
    await signOut();
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/api\/v1\/auth\/logout$/);
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
    expect((init.headers as Record<string, string>)["X-Agentmetry-Request"]).toBe("1");
  });

  it("does not throw when the recorder is down", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("connection refused"))));
    await expect(signOut()).resolves.toBeUndefined();
  });
});
