"use client";

import { useCallback, useEffect, useState } from "react";
import { useAgentStore } from "@/lib/store";
import { ORCHESTRATOR_URL } from "@/lib/utils";
import { apiPost } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface PendingApproval {
  thread_id: string;
  skill_name: string;
  confidence: number;
  draft: string;
}

export function PendingApprovalsPanel() {
  const runsRefreshKey = useAgentStore((s) => s.runsRefreshKey);
  const bumpRunsRefresh = useAgentStore((s) => s.bumpRunsRefresh);
  const [items, setItems] = useState<PendingApproval[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);

  const fetchItems = useCallback(() => {
    fetch(`${ORCHESTRATOR_URL}/api/v1/skills/pending`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => setItems(data.pending || []))
      .catch(() => setItems([]));
  }, []);

  useEffect(() => {
    fetchItems();
    const interval = setInterval(fetchItems, 30000);
    return () => clearInterval(interval);
  }, [fetchItems, runsRefreshKey]);

  useEffect(() => {
    const live = new Set(items.map((i) => i.thread_id));
    setSelected((prev) => new Set(Array.from(prev).filter((id) => live.has(id))));
  }, [items]);

  const resolveBatch = useCallback(
    async (approved: boolean, threadIds?: string[]) => {
      const ids =
        threadIds ??
        items.map((i) => i.thread_id).filter((id) => selected.has(id));
      if (ids.length === 0) return;
      setBusy(true);
      try {
        await apiPost("/api/v1/skills/approve/batch", { thread_ids: ids, approved });
      } finally {
        setBusy(false);
        setSelected(new Set());
        fetchItems();
        bumpRunsRefresh();
      }
    },
    [items, selected, fetchItems, bumpRunsRefresh]
  );

  useEffect(() => {
    if (items.length === 0 || busy) return;

    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

      if (e.key === "a" && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        if (e.shiftKey) {
          void resolveBatch(true, items.map((i) => i.thread_id));
        } else {
          const ids = items
            .map((i) => i.thread_id)
            .filter((id) => selected.has(id));
          if (ids.length === 0 && items.length === 1) {
            void resolveBatch(true, [items[0].thread_id]);
          } else if (ids.length > 0) {
            void resolveBatch(true, ids);
          }
        }
      } else if (e.key === "r" && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        const ids = items
          .map((i) => i.thread_id)
          .filter((id) => selected.has(id));
        if (ids.length > 0) {
          void resolveBatch(false, ids);
        }
      } else if (e.key === "x" && !e.metaKey && !e.ctrlKey && !e.altKey) {
        const focused = items[0]?.thread_id;
        if (!focused) return;
        setSelected((prev) => {
          const next = new Set(prev);
          next.has(focused) ? next.delete(focused) : next.add(focused);
          return next;
        });
      }
    };

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [items, busy, selected, resolveBatch]);

  if (items.length === 0) return null;

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const allSelected = selected.size === items.length;
  const toggleAll = () =>
    setSelected(allSelected ? new Set() : new Set(items.map((i) => i.thread_id)));

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center justify-between">
          <span>
            Approvals <span className="text-muted-foreground/60">· Gate</span>
          </span>
          <button
            className="text-xs font-normal text-muted-foreground hover:text-foreground"
            onClick={toggleAll}
          >
            {allSelected ? "clear" : "all"} ({items.length})
          </button>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-xs">
        {items.map((item) => (
          <label
            key={item.thread_id}
            className="flex items-center gap-2 font-mono cursor-pointer"
            title={item.draft?.slice(0, 400)}
          >
            <input
              type="checkbox"
              checked={selected.has(item.thread_id)}
              onChange={() => toggle(item.thread_id)}
            />
            <span className="truncate flex-1">{item.skill_name}</span>
            {item.draft?.trim() ? (
              <span className="text-muted-foreground">draft</span>
            ) : (
              <span className="text-violet-400/80">tool gate</span>
            )}
          </label>
        ))}
        <p className="text-[10px] text-muted-foreground/70 pt-0.5">
          Keys: a approve · Shift+a all · r reject checked
        </p>
        <div className="flex gap-2 pt-1">
          <button
            className="flex-1 rounded border border-border px-2 py-0.5 text-green-400 hover:bg-muted disabled:opacity-40"
            disabled={busy || selected.size === 0}
            onClick={() => resolveBatch(true)}
          >
            Approve {selected.size || ""}
          </button>
          <button
            className="flex-1 rounded border border-border px-2 py-0.5 text-red-400 hover:bg-muted disabled:opacity-40"
            disabled={busy || selected.size === 0}
            onClick={() => resolveBatch(false)}
          >
            Reject {selected.size || ""}
          </button>
        </div>
      </CardContent>
    </Card>
  );
}
