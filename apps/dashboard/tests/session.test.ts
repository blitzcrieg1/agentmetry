import { afterEach, describe, expect, it, vi } from "vitest";

import { checkSession, readSession, signOut } from "@/lib/session";

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

describe("demo label", () => {
  const body = (status: number, json: unknown) =>
    vi.fn(async () => new Response(JSON.stringify(json), { status }));

  it("takes the demo flag from the server, not the page URL", async () => {
    vi.stubGlobal("fetch", body(200, { demo: true }));
    expect(await readSession()).toEqual({ state: "signed_in", demo: true });
    vi.stubGlobal("fetch", body(200, { demo: false }));
    expect(await readSession()).toEqual({ state: "signed_in", demo: false });
  });

  it("treats an older server without the field as live", async () => {
    vi.stubGlobal("fetch", body(200, {}));
    expect((await readSession()).demo).toBe(false);
  });

  it("claims neither until a signed-in answer arrives", async () => {
    vi.stubGlobal("fetch", body(401, {}));
    expect((await readSession()).demo).toBeNull();
    vi.stubGlobal("fetch", body(500, {}));
    expect((await readSession()).demo).toBeNull();
  });
});
