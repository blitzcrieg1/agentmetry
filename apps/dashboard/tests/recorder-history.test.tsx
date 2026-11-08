import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FlightRecorderPanel } from "@/components/flight-recorder-panel";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;

async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function goTo(hash: string) {
  window.history.pushState(null, "", hash);
  await act(async () => { window.dispatchEvent(new HashChangeEvent("hashchange")); });
  await settle();
}

const sessionCalls = () => vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes("/audit/session/")).length;
const inSession = () => (host.textContent ?? "").includes("Back to live");

function recordedEvent(command: string) {
  return {
    event_id: command,
    correlation_id: "demo-session",
    timestamp_utc: new Date().toISOString(),
    action: { type: "tool_called", outcome: "success" },
    tool: { name: "Read", command },
    source: { app: "claude" },
  };
}

function eventResponse(command: string) {
  return new Response(JSON.stringify({ events: [recordedEvent(command)], pagination: {} }), { status: 200 });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

beforeEach(async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ events: [], pagination: {} }), { status: 200 })));
  host = document.createElement("div");
  document.body.appendChild(host);
  window.history.replaceState(null, "", "#page=recorder");
  root = createRoot(host);
  await act(async () => root.render(createElement(FlightRecorderPanel)));
  await settle();
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

describe("Back and Forward in the event stream", () => {
  it("opens a session the URL names and leaves it when the URL stops naming it", async () => {
    expect(inSession()).toBe(false);
    await goTo("#page=recorder&session=demo-session");
    expect(inSession()).toBe(true);
    expect(sessionCalls()).toBe(1);
    await goTo("#page=recorder");
    expect(inSession()).toBe(false);
  });

  it("does not refetch a session that is already open", async () => {
    await goTo("#page=recorder&session=demo-session");
    await act(async () => { window.dispatchEvent(new HashChangeEvent("hashchange")); });
    await settle();
    expect(sessionCalls()).toBe(1);
  });

  it("ignores a session response that arrives after Back returns to live", async () => {
    const pending = deferred<Response>();
    vi.mocked(fetch).mockImplementation(async (url) => {
      if (String(url).includes("/audit/session/")) return pending.promise;
      return eventResponse("demo-live-marker");
    });
    await goTo("#page=recorder&session=demo-session");
    await goTo("#page=recorder");
    expect(host.textContent).toContain("demo-live-marker");
    await act(async () => pending.resolve(eventResponse("demo-old-session-marker")));
    await settle();
    expect(inSession()).toBe(false);
    expect(host.textContent).toContain("demo-live-marker");
    expect(host.textContent).not.toContain("demo-old-session-marker");
  });

  it("ignores a previous session when another session loads first", async () => {
    const pending = deferred<Response>();
    vi.mocked(fetch).mockImplementation(async (url) => {
      if (String(url).includes("/audit/session/demo-old")) return pending.promise;
      return eventResponse("demo-current-session-marker");
    });
    await goTo("#page=recorder&session=demo-old");
    await goTo("#page=recorder&session=demo-current");
    await act(async () => pending.resolve(eventResponse("demo-old-session-marker")));
    await settle();
    expect(host.textContent).toContain("demo-current-session-marker");
    expect(host.textContent).not.toContain("demo-old-session-marker");
  });

  it("ignores a live-feed response that arrives after a session opens", async () => {
    const pending = deferred<Response>();
    vi.mocked(fetch).mockImplementation(async (url) => {
      if (String(url).includes("/audit/tail")) return pending.promise;
      return eventResponse("demo-current-session-marker");
    });
    const refresh = Array.from(host.querySelectorAll("button")).find((button) => button.textContent === "Refresh")!;
    await act(async () => refresh.click());
    await goTo("#page=recorder&session=demo-current");
    await act(async () => pending.resolve(eventResponse("demo-old-live-marker")));
    await settle();
    expect(inSession()).toBe(true);
    expect(host.textContent).toContain("demo-current-session-marker");
    expect(host.textContent).not.toContain("demo-old-live-marker");
  });

  it("ignores an old session error after returning to live", async () => {
    const pending = deferred<Response>();
    vi.mocked(fetch).mockImplementation(async (url) => {
      if (String(url).includes("/audit/session/")) return pending.promise;
      return eventResponse("demo-live-marker");
    });
    await goTo("#page=recorder&session=demo-session");
    await goTo("#page=recorder");
    await act(async () => pending.reject(new Error("demo-old-request-error")));
    await settle();
    expect(host.textContent).toContain("demo-live-marker");
    expect(host.textContent).not.toContain("demo-old-request-error");
    expect(host.textContent).not.toContain("Refresh failed");
  });

  it("refreshes the pinned session rather than loading live rows under its banner", async () => {
    await goTo("#page=recorder&session=demo-session");
    const calls = sessionCalls();
    const refresh = Array.from(host.querySelectorAll("button")).find((button) => button.textContent === "Refresh")!;
    await act(async () => refresh.click());
    await settle();
    expect(sessionCalls()).toBe(calls + 1);
    expect(inSession()).toBe(true);
  });

  it("leaves the pinned session when Latest is clicked", async () => {
    await goTo("#page=recorder&session=demo-session");
    const latest = Array.from(host.querySelectorAll("button")).find((button) => button.textContent?.trim() === "Latest")!;
    await act(async () => latest.click());
    await settle();
    expect(inSession()).toBe(false);
    expect(window.location.hash).toBe("#page=recorder");
  });
});
