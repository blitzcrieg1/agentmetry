"use client";

import { Bot, Eye, EyeOff, Monitor, PanelLeftClose, PanelLeftOpen, ShieldAlert, TerminalSquare, TriangleAlert, Zap } from "lucide-react";
import { FAMILY_ICON } from "@/components/investigation/family-icon";
import type { FamilyCount, Highlight } from "@/lib/investigation";

/**
 * The left panel: what the session holds, which tool categories are drawn, and
 * what to light up. Hiding a category takes it out of the tree, graph, table
 * and timeline together; highlighting dims everything that does not match.
 */
export function Legend({
  collapsed,
  onCollapse,
  detections,
  host,
  agent,
  families,
  hidden,
  onToggle,
  highlight,
  onHighlight,
  highlightCounts,
}: {
  collapsed: boolean;
  onCollapse: (collapsed: boolean) => void;
  detections: number;
  host: string;
  agent: string;
  families: FamilyCount[];
  hidden: ReadonlySet<string>;
  onToggle: (key: string) => void;
  highlight: Highlight | null;
  onHighlight: (h: Highlight | null) => void;
  highlightCounts: Record<Highlight, number>;
}) {
  if (collapsed) {
    return (
      <div className="panel flex w-11 shrink-0 flex-col items-center gap-2 py-2">
        <button type="button" className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground" onClick={() => onCollapse(false)} aria-label="Show legend" title="Show legend">
          <PanelLeftOpen className="h-4 w-4" />
        </button>
      </div>
    );
  }
  const calls = families.reduce((n, f) => n + f.calls, 0);
  const entities: { label: string; value: string | number; icon: typeof Monitor; tone?: string }[] = [
    { label: "Detections here", value: detections, icon: ShieldAlert, tone: "text-danger" },
    { label: "Machine", value: host || "1", icon: Monitor },
    { label: "Agent", value: agent || "1", icon: Bot },
    { label: "Session", value: 1, icon: TerminalSquare },
    { label: "Recorded events", value: calls.toLocaleString(), icon: Zap },
  ];
  const highlights: { id: Highlight; label: string; tone: string }[] = [
    { id: "cited", label: "Cited evidence", tone: "bg-danger" },
    { id: "flagged", label: "Refused, policy or DLP", tone: "bg-caution" },
    { id: "errors", label: "Errors", tone: "bg-danger/60" },
  ];

  return (
    <aside className="panel flex w-64 shrink-0 flex-col overflow-y-auto" aria-label="Legend">
      <div className="flex items-center justify-between border-b border-border px-3 py-2.5">
        <h3 className="text-[13px] font-semibold">Legend</h3>
        <button type="button" className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground" onClick={() => onCollapse(true)} aria-label="Hide legend" title="Hide legend">
          <PanelLeftClose className="h-4 w-4" />
        </button>
      </div>

      <ul className="divide-y divide-border border-b border-border">
        {entities.map(({ label, value, icon: Icon, tone }) => (
          <li key={label} className="flex items-center gap-2.5 px-3 py-2 text-[12px]">
            <Icon className={`h-4 w-4 shrink-0 ${tone ?? "text-muted-foreground"}`} aria-hidden />
            <span className="flex-1 text-muted-foreground">{label}</span>
            <span className="max-w-[7rem] truncate font-mono text-foreground" title={String(value)}>{value}</span>
          </li>
        ))}
      </ul>

      <div className="border-b border-border px-3 pb-1 pt-3">
        <p className="eyebrow">Show categories</p>
      </div>
      <ul className="divide-y divide-border border-b border-border">
        {families.map((f) => {
          const Icon = FAMILY_ICON[f.family];
          const off = hidden.has(f.key);
          return (
            <li key={f.key}>
              <button
                type="button"
                aria-pressed={!off}
                onClick={() => onToggle(f.key)}
                className={`flex w-full items-center gap-2.5 px-3 py-2 text-left text-[12px] transition-colors hover:bg-muted/60 ${off ? "text-subtle" : ""}`}
                title={off ? `Show ${f.label}` : `Hide ${f.label}`}
              >
                <Icon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                <span className={`flex-1 truncate ${off ? "line-through" : ""}`}>{f.label}</span>
                {f.cited ? <ShieldAlert className="h-3.5 w-3.5 text-danger" aria-label="Holds cited evidence" /> : null}
                <span className="font-mono text-muted-foreground">{f.calls.toLocaleString()}</span>
                {off ? <EyeOff className="h-3.5 w-3.5 text-subtle" aria-hidden /> : <Eye className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />}
              </button>
            </li>
          );
        })}
      </ul>

      <div className="px-3 pb-1 pt-3">
        <p className="eyebrow">Highlight by</p>
      </div>
      <ul className="divide-y divide-border">
        {highlights.map(({ id, label, tone }) => (
          <li key={id}>
            <button
              type="button"
              aria-pressed={highlight === id}
              disabled={!highlightCounts[id]}
              onClick={() => onHighlight(highlight === id ? null : id)}
              className={`flex w-full items-center gap-2.5 px-3 py-2 text-left text-[12px] transition-colors hover:bg-muted/60 disabled:cursor-default disabled:opacity-50 disabled:hover:bg-transparent ${
                highlight === id ? "bg-muted font-medium" : ""
              }`}
            >
              <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${tone}`} aria-hidden />
              <span className="flex-1">{label}</span>
              <span className="font-mono text-muted-foreground">{highlightCounts[id]}</span>
            </button>
          </li>
        ))}
      </ul>
      <p className="mt-auto flex items-start gap-1.5 border-t border-border px-3 py-2.5 text-[12px] leading-relaxed text-subtle">
        <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
        Agent tool activity, recorded at the hook. Not operating-system process ancestry.
      </p>
    </aside>
  );
}
