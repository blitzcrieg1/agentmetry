"use client";

import { useMemo, useState } from "react";
import { Plus, X } from "lucide-react";
import { SIGNAL_LABEL, kindLabel, signalOf } from "@/lib/investigation";
import { type SessionNode, shortTool, toolFamily } from "@/lib/session-tree";
import { sourceLabel } from "@/lib/audit-source";

const PAGE = 100;

function stamp(ts: string): string {
  const d = new Date(ts);
  return Number.isNaN(d.getTime())
    ? ts
    : d.toLocaleString(undefined, { month: "short", day: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/**
 * Every loaded event in time order, as a table. Chips choose which kinds of
 * event are listed, the switch narrows it to the selected call's category, and
 * the page opens on the first cited event rather than the session's first line.
 */
export function EventsTimeline({
  nodes,
  cited,
  selected,
  onSelect,
  truncated,
  total,
}: {
  nodes: SessionNode[];
  cited: Set<string>;
  selected: SessionNode | null;
  onSelect: (id: string) => void;
  truncated: boolean;
  total?: number;
}) {
  const kinds = useMemo(() => [...new Set(nodes.map(kindLabel))].sort(), [nodes]);
  const [off, setOff] = useState<Set<string>>(new Set());
  const [selectionOnly, setSelectionOnly] = useState(false);
  const [newestFirst, setNewestFirst] = useState(false);
  const selectedFamily = selected ? toolFamily(selected).key : null;

  const ordered = useMemo(() => {
    const list = nodes.filter(
      (n) => !off.has(kindLabel(n)) && (!selectionOnly || !selectedFamily || toolFamily(n).key === selectedFamily),
    );
    list.sort((a, b) => a.timestamp_utc.localeCompare(b.timestamp_utc));
    if (newestFirst) list.reverse();
    return list;
  }, [nodes, off, selectionOnly, selectedFamily, newestFirst]);

  const firstCited = ordered.findIndex((n) => signalOf(n, cited) === "cited");
  const opening = Math.max(0, Math.min(Math.max(0, ordered.length - PAGE), firstCited >= 0 ? firstCited - PAGE / 2 : 0));
  const [startOverride, setStartOverride] = useState<number | null>(null);
  const start = Math.min(startOverride ?? opening, Math.max(0, ordered.length - 1));
  const visible = ordered.slice(start, start + PAGE);

  const toggleKind = (k: string) => {
    setStartOverride(null);
    setOff((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  };

  return (
    <section className="flex min-h-0 flex-1 flex-col" aria-label="Events timeline">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2.5">
        <label className="mr-2 inline-flex cursor-pointer items-center gap-2 text-[12px]">
          <span className="text-muted-foreground">Show events for selection only</span>
          <button
            type="button"
            role="switch"
            aria-checked={selectionOnly}
            disabled={!selected}
            onClick={() => {
              setSelectionOnly(!selectionOnly);
              setStartOverride(null);
            }}
            className={`relative h-5 w-9 rounded-full transition-colors disabled:opacity-40 ${selectionOnly ? "bg-signal" : "bg-muted"}`}
          >
            <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-background shadow transition-all ${selectionOnly ? "left-[1.1rem]" : "left-0.5"}`} />
          </button>
        </label>
        {kinds.map((k) =>
          off.has(k) ? (
            <button key={k} type="button" onClick={() => toggleKind(k)} className="inline-flex items-center gap-1 rounded-md border border-dashed border-border px-2 py-1 text-[12px] text-subtle hover:text-foreground">
              <Plus className="h-3 w-3" aria-hidden /> {k}
            </button>
          ) : (
            <span key={k} className="inline-flex items-center gap-1 rounded-md border border-border bg-muted/50 py-1 pl-2 pr-1 text-[12px]">
              {k}
              <button type="button" onClick={() => toggleKind(k)} className="rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground" aria-label={`Hide ${k}`}>
                <X className="h-3 w-3" />
              </button>
            </span>
          ),
        )}
        <select
          aria-label="Sort"
          className="control ml-auto h-8 text-[12px]"
          value={newestFirst ? "newest" : "oldest"}
          onChange={(e) => {
            setNewestFirst(e.target.value === "newest");
            setStartOverride(0);
          }}
        >
          <option value="oldest">Time: oldest to newest</option>
          <option value="newest">Time: newest to oldest</option>
        </select>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full min-w-[820px] border-collapse text-left text-[12px]">
          <thead className="sticky top-0 z-10 bg-card">
            <tr className="border-b border-border text-subtle">
              <th className="w-48 px-3 py-2 font-medium">Time</th>
              <th className="w-6" />
              <th className="px-3 py-2 font-medium">Event</th>
              <th className="px-3 py-2 font-medium">Tool</th>
              <th className="px-3 py-2 font-medium">Recorded input</th>
              <th className="px-3 py-2 font-medium">Outcome</th>
              <th className="px-3 py-2 font-medium">Signal</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((n, i) => {
              const s = signalOf(n, cited);
              const isSel = n.id === selected?.id;
              return (
                <tr
                  key={n.id}
                  tabIndex={0}
                  role="button"
                  aria-pressed={isSel}
                  onClick={() => onSelect(n.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onSelect(n.id);
                    }
                  }}
                  className={`cursor-pointer border-b border-border/60 outline-none transition-colors hover:bg-muted/50 focus-visible:bg-muted/60 ${
                    isSel ? "bg-signal/[0.08]" : s === "cited" ? "bg-danger/[0.04]" : ""
                  }`}
                >
                  <td className="whitespace-nowrap px-3 py-2 font-mono text-muted-foreground">{stamp(n.timestamp_utc)}</td>
                  <td className="relative px-0">
                    <span className={`absolute left-1/2 w-px -translate-x-1/2 bg-border ${i === 0 ? "top-1/2" : "top-0"} ${i === visible.length - 1 ? "bottom-1/2" : "bottom-0"}`} aria-hidden />
                    <span
                      className={`relative z-[1] mx-auto block h-2.5 w-2.5 rounded-full ring-4 ring-card ${s === "cited" ? "bg-danger" : s ? "bg-caution" : "bg-subtle"}`}
                      aria-hidden
                    />
                  </td>
                  <td className="whitespace-nowrap px-3 py-2">{kindLabel(n)}</td>
                  <td className="whitespace-nowrap px-3 py-2 font-mono font-medium">{shortTool(n)}<span className="ml-1.5 font-sans font-normal text-subtle">{sourceLabel(n.app)}</span></td>
                  <td className="max-w-[24rem] px-3 py-2 font-mono text-muted-foreground"><span className="block truncate" title={n.tool.command || n.reason}>{n.tool.command || n.reason || "—"}</span></td>
                  <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">{n.kind === "denied" ? "denied" : n.outcome || "recorded"}</td>
                  <td className="whitespace-nowrap px-3 py-2">
                    {s ? <span className={`rounded-sm px-1.5 py-0.5 ${s === "cited" ? "bg-danger/10 text-danger" : "bg-caution/10 text-caution"}`}>{SIGNAL_LABEL[s]}</span> : <span className="text-subtle">—</span>}
                  </td>
                </tr>
              );
            })}
            {!visible.length ? (
              <tr><td colSpan={7} className="px-4 py-12 text-center text-muted-foreground">No events match these filters.</td></tr>
            ) : null}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-4 py-2 text-[12px] text-subtle">
        <span>
          {ordered.length ? `${(start + 1).toLocaleString()}–${Math.min(start + PAGE, ordered.length).toLocaleString()}` : "0"} of {ordered.length.toLocaleString()} events
          {truncated ? <span className="ml-2 text-caution">A window of a longer session{total ? ` (${total.toLocaleString()} in all)` : ""}. The event stream has the rest.</span> : null}
        </span>
        <span className="flex gap-2">
          <button type="button" className="btn h-8" disabled={start === 0} onClick={() => setStartOverride(Math.max(0, start - PAGE))}>Previous {PAGE}</button>
          <button type="button" className="btn h-8" disabled={start + PAGE >= ordered.length} onClick={() => setStartOverride(start + PAGE)}>Next {PAGE}</button>
        </span>
      </div>
    </section>
  );
}
