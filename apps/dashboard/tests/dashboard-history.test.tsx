import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DetectionsPanel } from "@/components/detections-panel";
import { type Destination, forwardingStatus } from "@/components/forwarding-panel";
import { ReportedAccount } from "@/components/reported-account";

// The investigation has its own views and fetches. These tests are about when it opens.
vi.mock("@/components/detection-investigation", () => ({
  DetectionInvestigation: () => createElement("div", { "data-testid": "investigation" }),
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const DETECTION_EVENT = {
  action: { type: "detection", outcome: "success" },
  correlation_id: "demo-session",
  detection: {
    rule_id: "demo-rule",
    title: "Demo detection",
    summary: "An invented detection",
    severity: "high",
    correlation_id: "demo-session",
    first_seen_utc: "2026-11-08T10:00:00Z",
    last_seen_utc: "2026-11-08T10:01:00Z",
  },
};

let root: Root | null = null;
let host: HTMLDivElement;

function respondWith(events: unknown[], ok = true) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ events, pagination: {}, dispositions: [] }), { status: ok ? 200 : 500 })));
}

async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function mount(props: Parameters<typeof DetectionsPanel>[0] = {}) {
  root = createRoot(host);
  await act(async () => root!.render(createElement(DetectionsPanel, props)));
  await settle();
}

async function goTo(hash: string) {
  window.history.pushState(null, "", hash);
  await act(async () => { window.dispatchEvent(new HashChangeEvent("hashchange")); });
  await settle();
}

async function search(value: string) {
  const input = host.querySelector<HTMLInputElement>('input[aria-label="Search detections"]')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

const investigationOpen = () => Boolean(host.querySelector('[data-testid="investigation"]'));
const searchValue = () => host.querySelector<HTMLInputElement>('input[aria-label="Search detections"]')?.value;

beforeEach(() => {
  host = document.createElement("div");
  document.body.appendChild(host);
  window.history.replaceState(null, "", "#page=detections");
});

afterEach(async () => {
  await act(async () => root?.unmount());
  root = null;
  host.remove();
  vi.unstubAllGlobals();
});

describe("Back and Forward on the Detections page", () => {
  it("keeps the analyst's search when the investigation closes", async () => {
    respondWith([DETECTION_EVENT]);
    await mount();
    await search("demo");
    await goTo("#page=detections&session=demo-session&rule=demo-rule");
    expect(investigationOpen()).toBe(true);
    await goTo("#page=detections");
    expect(investigationOpen()).toBe(false);
    expect(searchValue()).toBe("demo");
  });

  it("does not refetch to follow the URL", async () => {
    respondWith([DETECTION_EVENT]);
    await mount();
    const calls = vi.mocked(fetch).mock.calls.length;
    await goTo("#page=detections&session=demo-session&rule=demo-rule");
    await goTo("#page=detections");
    expect(vi.mocked(fetch).mock.calls.length).toBe(calls);
  });
});

describe("a link to a detection", () => {
  const link = { correlationId: "demo-session", ruleId: "demo-rule" };

  it("opens the detection it names", async () => {
    respondWith([DETECTION_EVENT]);
    await mount({ initialDetection: link });
    expect(investigationOpen()).toBe(true);
    expect(host.textContent).not.toContain("not in this view");
  });

  it("says so when the detection is not there", async () => {
    respondWith([DETECTION_EVENT]);
    await mount({ initialDetection: { correlationId: "gone", ruleId: "demo-rule" } });
    expect(investigationOpen()).toBe(false);
    expect(host.textContent).toContain("The linked detection is not in this view");
  });

  it("does not call a detection missing when the load failed", async () => {
    respondWith([], false);
    await mount({ initialDetection: link });
    expect(host.textContent).not.toContain("not in this view");
  });
});

describe("forwarding status", () => {
  const healthy: Destination = { seq: 40, forwarded: 40, dead_lettered: 0, failing_for_seconds: 0, last_error: "" };

  it("reports no failure only when nothing was refused", () => {
    expect(forwardingStatus(healthy)).toEqual({ text: "No failure reported", attention: false });
  });

  it("treats a refused event as a failure even when retries are clear", () => {
    expect(forwardingStatus({ ...healthy, dead_lettered: 5 })).toEqual({ text: "5 events refused and dead-lettered", attention: true });
    expect(forwardingStatus({ ...healthy, dead_lettered: 1 }).text).toBe("1 event refused and dead-lettered");
  });

  it("reports retrying and refused together", () => {
    const status = forwardingStatus({ ...healthy, dead_lettered: 2, failing_for_seconds: 12.1, last_error: "synthetic" });
    expect(status.text).toContain("Retrying · failing for 13 s");
    expect(status.text).toContain("2 events refused");
    expect(status.attention).toBe(true);
  });
});

describe("Codex account provenance", () => {
  it("attributes the IDs to the session file, not the sign-in file", () => {
    const account = { domain: "example.com", source: "codex_auth", account_id: "demo-account", user_id: "demo-user" };
    const html = renderToStaticMarkup(createElement(ReportedAccount, { account }));
    expect(html).toContain("Account ID (session file)");
    expect(html).toContain("User ID (session file)");
    expect(html).toContain("Any IDs come from the session file");
  });

  it("does not add that attribution to other sources", () => {
    const account = { domain: "example.com", source: "local_config", account_id: "demo-account" };
    expect(renderToStaticMarkup(createElement(ReportedAccount, { account }))).not.toContain("(session file)");
  });
});
