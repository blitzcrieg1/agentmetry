"use client";

import { type ReactNode, useState } from "react";
import { Check, ChevronDown, ChevronUp, Copy, ExternalLink, PanelRightClose, PanelRightOpen, ShieldAlert } from "lucide-react";
import type { Detection } from "@/components/flight-recorder-panel";
import { SeverityBadge, Technique } from "@/components/ui/kit";
import { TriagePanel, formatTime } from "@/components/triage-panel";
import { sourceLabel } from "@/lib/audit-source";
import type { Disposition } from "@/lib/disposition";
import {
  type Entity,
  type FamilyCount,
  SIGNAL_LABEL,
  dlpSentence,
  kindLabel,
  policySentence,
  shortSession,
  signalOf,
} from "@/lib/investigation";
import { type SessionNode, approvalSentence, toolFamily } from "@/lib/session-tree";

export function CopyButton({ value, label }: { value: string; label: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      className="shrink-0 rounded-md border border-border p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      aria-label={`Copy ${label}`}
      title={`Copy ${label}`}
      onClick={() => {
        void navigator.clipboard?.writeText(value).then(() => {
          setDone(true);
          window.setTimeout(() => setDone(false), 1200);
        });
      }}
    >
      {done ? <Check className="h-3.5 w-3.5 text-secure" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  );
}

export function CodeField({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="space-y-1">
      <p className="eyebrow">{label}</p>
      <div className="flex items-start gap-2 rounded-md border border-border bg-background px-2.5 py-2">
        <code className="max-h-40 min-w-0 flex-1 overflow-auto whitespace-pre-wrap break-all font-mono text-[12px] leading-relaxed text-signal">{value}</code>
        <CopyButton value={value} label={label.toLowerCase()} />
      </div>
      {note ? <p className="text-[12px] text-subtle">{note}</p> : null}
    </div>
  );
}

function Section({ title, icon, children, defaultOpen = true }: { title: string; icon?: ReactNode; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const Chevron = open ? ChevronUp : ChevronDown;
  return (
    <section className="border-b border-border">
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 px-4 py-3 text-left hover:bg-muted/40">
        {icon}
        <span className="flex-1 text-[13px] font-semibold">{title}</span>
        <Chevron className="h-4 w-4 text-muted-foreground" aria-hidden />
      </button>
      {open ? <div className="space-y-3 px-4 pb-4">{children}</div> : null}
    </section>
  );
}

function Facts({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
      {rows.map(([k, v]) => (
        <div key={k} className="min-w-0">
          <dt className="eyebrow">{k}</dt>
          <dd className="mt-0.5 truncate text-[13px]">{v || "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

export interface DrawerContext {
  det: Detection;
  disposition?: Disposition;
  onDispositionSaved: (d: Disposition) => void;
  onOpenInStream: () => void;
  host: string;
  sessionId: string;
  cited: Set<string>;
  detectionsInSession: SessionNode[];
  families: FamilyCount[];
}

/**
 * The right panel: whatever is selected, in sections that open and close, with
 * the values an analyst copies into a ticket one click away. Triage stays at
 * the bottom of every view, so a decision never needs a tab change.
 */
export function Drawer({
  collapsed,
  onCollapse,
  selected,
  entity,
  ctx,
}: {
  collapsed: boolean;
  onCollapse: (collapsed: boolean) => void;
  selected: SessionNode | null;
  entity: Entity | null;
  ctx: DrawerContext;
}) {
  if (collapsed) {
    return (
      <div className="panel flex w-11 shrink-0 flex-col items-center gap-2 py-2">
        <button type="button" className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground" onClick={() => onCollapse(false)} aria-label="Show details panel" title="Show details panel">
          <PanelRightOpen className="h-4 w-4" />
        </button>
      </div>
    );
  }
  const title = selected ? selected.tool.qualified || kindLabel(selected) : entity?.label ?? "Session";
  return (
    <aside className="panel flex w-full shrink-0 flex-col overflow-hidden xl:w-[25rem]" aria-label="Details">
      <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
        <h3 className="min-w-0 flex-1 truncate font-mono text-[13px] font-semibold" title={title}>{title}</h3>
        <button type="button" className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground" onClick={() => onCollapse(true)} aria-label="Hide details panel" title="Hide details panel">
          <PanelRightClose className="h-4 w-4" />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {selected ? <CallDetail node={selected} ctx={ctx} /> : <EntityDetail entity={entity} ctx={ctx} />}
        <Section title="Associated detections" icon={<ShieldAlert className="h-4 w-4 text-danger" aria-hidden />}>
          <AssociatedDetections ctx={ctx} />
        </Section>
        <Section title="Triage">
          <TriagePanel det={ctx.det} disposition={ctx.disposition} onSaved={ctx.onDispositionSaved} />
          <button type="button" onClick={ctx.onOpenInStream} className="btn w-full">
            <ExternalLink className="h-3.5 w-3.5" />
            View session in event stream
          </button>
        </Section>
      </div>
    </aside>
  );
}

function CallDetail({ node, ctx }: { node: SessionNode; ctx: DrawerContext }) {
  const signal = signalOf(node, ctx.cited);
  const family = toolFamily(node);
  const approval = approvalSentence(node);
  const policy = policySentence(node);
  const dlp = dlpSentence(node);
  return (
    <>
      <div className={`flex items-center gap-2 border-b border-border px-4 py-2.5 ${signal === "cited" ? "bg-danger/[0.06]" : signal ? "bg-caution/[0.05]" : ""}`}>
        {signal === "cited" ? (
          <>
            <ShieldAlert className="h-4 w-4 text-danger" aria-hidden />
            <span className="text-[13px] font-semibold text-danger">Cited by this detection</span>
            <SeverityBadge severity={ctx.det.severity} className="ml-auto" />
          </>
        ) : signal ? (
          <span className="text-[13px] font-semibold text-caution">{SIGNAL_LABEL[signal]}</span>
        ) : (
          <span className="text-[13px] text-muted-foreground">Recorded call, not cited by this detection</span>
        )}
      </div>
      <Section title="Execution details">
        <Facts
          rows={[
            ["Agent", sourceLabel(node.app) || node.app],
            ["Adapter", <span key="a" className="font-mono">{node.adapter}</span>],
            ["Machine", ctx.host],
            ["Session", <span key="s" className="font-mono" title={ctx.sessionId}>{shortSession(ctx.sessionId)}</span>],
            ["Time", formatTime(node.timestamp_utc)],
            ["Outcome", node.kind === "denied" ? "denied" : node.outcome || "recorded"],
            ["Category", family.label],
            ["Event", kindLabel(node)],
          ]}
        />
        {node.asked_as && node.asked_as !== node.tool.qualified ? (
          <p className="text-[12px] text-muted-foreground">Asked as <span className="font-mono">{node.asked_as}</span></p>
        ) : null}
      </Section>
      <Section title="Recorded input">
        {node.tool.command ? (
          <CodeField label="Command line" value={node.tool.command} note={node.tool.command_truncated ? "Cut at 4,000 characters." : undefined} />
        ) : family.family === "shell" ? (
          <p className="rounded-md border border-dashed border-border p-2.5 text-[12px] leading-relaxed text-muted-foreground">
            Command text is not recorded. The trail keeps a hash of the arguments; set AGENTMETRY_LOG_COMMANDS=1 to keep the command line as well.
          </p>
        ) : (
          <p className="text-[12px] text-muted-foreground">No input text was recorded for this call.</p>
        )}
        {node.tool.input_hash ? <CodeField label="Input hash (SHA-256)" value={node.tool.input_hash} /> : null}
      </Section>
      {node.tool.mitre?.technique_id || approval || policy || dlp ? (
        <Section title="Context">
          {node.tool.mitre?.technique_id ? (
            <div className="space-y-1">
              <p className="eyebrow">ATT&amp;CK</p>
              <p className="flex flex-wrap items-center gap-2 text-[13px]">
                <Technique id={node.tool.mitre.technique_id} tone={signal === "cited" ? "alert" : "default"} />
                {node.tool.mitre.technique}
                {node.tool.mitre.tactic ? <span className="text-muted-foreground">({node.tool.mitre.tactic})</span> : null}
              </p>
            </div>
          ) : null}
          {approval ? <p className="text-[12px] leading-relaxed text-muted-foreground">{approval}</p> : null}
          {policy ? <p className="text-[12px] leading-relaxed text-caution">{policy}</p> : null}
          {dlp ? <p className="text-[12px] leading-relaxed text-caution">{dlp}</p> : null}
        </Section>
      ) : null}
      <Section title="Event IDs" defaultOpen={false}>
        <ul className="space-y-1.5">
          {node.event_ids.map((id) => (
            <li key={id} className="flex items-center gap-2">
              <code className="min-w-0 flex-1 truncate font-mono text-[12px] text-muted-foreground" title={id}>{id}</code>
              <CopyButton value={id} label="event ID" />
            </li>
          ))}
        </ul>
      </Section>
    </>
  );
}

function EntityDetail({ entity, ctx }: { entity: Entity | null; ctx: DrawerContext }) {
  const rows = entity?.kind === "family" ? ctx.families.filter((f) => f.key === entity.familyKey) : ctx.families;
  const sum = (k: "calls" | "cited" | "flagged" | "refused" | "errors" | "asked") => rows.reduce((n, r) => n + r[k], 0);
  const scope =
    entity?.kind === "family" ? `the ${entity.label} category` : entity?.kind === "machine" ? "this machine's session" : entity?.kind === "agent" ? "this agent's session" : "this session";
  return (
    <Section title="Summary">
      <p className="text-[12px] text-muted-foreground">Counts for {scope}, from the events loaded for this investigation. Select a call to see its details.</p>
      <Facts
        rows={[
          ["Events", sum("calls").toLocaleString()],
          ["Cited", <span key="c" className={sum("cited") ? "text-danger" : ""}>{sum("cited")}</span>],
          ["Refused, policy or DLP", <span key="f" className={sum("flagged") ? "text-caution" : ""}>{sum("flagged")}</span>],
          ["Errors", sum("errors")],
          ["Asked for approval", sum("asked")],
          ["Refused", sum("refused")],
        ]}
      />
    </Section>
  );
}

function AssociatedDetections({ ctx }: { ctx: DrawerContext }) {
  const here = ctx.detectionsInSession;
  if (!here.length) {
    return <p className="text-[12px] text-muted-foreground">Only this detection fired in the loaded session window.</p>;
  }
  return (
    <ul className="space-y-2">
      {here.map((n) => {
        const d = n.detection ?? {};
        const current = d.rule_id === ctx.det.rule_id;
        return (
          <li key={n.id} className={`rounded-md border px-3 py-2 ${current ? "border-danger/40 bg-danger/[0.04]" : "border-border"}`}>
            <div className="flex items-center gap-2">
              {d.severity ? <SeverityBadge severity={d.severity} /> : null}
              <span className="min-w-0 flex-1 truncate text-[13px] font-medium">{d.title || d.rule_id}</span>
              {current ? <span className="text-[12px] text-subtle">this one</span> : null}
            </div>
            <p className="mt-1 font-mono text-[12px] text-subtle">{d.rule_id} · {formatTime(n.timestamp_utc)}</p>
          </li>
        );
      })}
    </ul>
  );
}
