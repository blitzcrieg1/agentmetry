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
});
