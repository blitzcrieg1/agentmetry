import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { parseDashboardLocation, writeDashboardLocation } from "@/lib/dashboard-location";
import { ReportedAccount } from "@/components/reported-account";
import { detectionsFromEvents, type AuditEvent } from "@/components/flight-recorder-panel";

describe("durable investigation locations", () => {
  it("round-trips session IDs and supports a graph view without a server route", () => {
    const location = { page: "detections" as const, session: "demo/session + 1", rule: "demo-rule", view: "graph" };
    writeDashboardLocation(location);
    expect(parseDashboardLocation(window.location.hash)).toEqual(location);
  });
  it("falls back safely when a page is unknown", () => {
    expect(parseDashboardLocation("#page=unknown").page).toBe("overview");
  });
  it("does not add duplicate history entries for the same location", () => {
    writeDashboardLocation({ page: "identity" });
    const length = window.history.length;
    writeDashboardLocation({ page: "identity" });
    expect(window.history.length).toBe(length);
  });
});

describe("account provenance in evidence", () => {
  it("keeps the detection event's claim and does not substitute a session-wide identity", () => {
    const account = { domain: "example.com", source: "hook_payload" };
    const event = { action: { type: "detection" }, account, detection: { rule_id: "demo", correlation_id: "demo-session" } } as AuditEvent;
    expect(detectionsFromEvents([event])[0].account).toEqual(account);
    expect(detectionsFromEvents([{ ...event, account: undefined }])[0].account).toBeUndefined();
  });
  it("renders an unknown state instead of a clean claim", () => {
    expect(renderToStaticMarkup(createElement(ReportedAccount))).toContain("Unknown. This event carried no account claim.");
  });
  it("explains stale local sign-in provenance and does not render an email field", () => {
    const claim = { domain: "example.com", source: "local_config", email: "invented@example.com" };
    const html = renderToStaticMarkup(createElement(ReportedAccount, { account: claim }));
    expect(html).toContain("Last sign-in on this machine");
    expect(html).not.toContain(claim.email);
  });
});
