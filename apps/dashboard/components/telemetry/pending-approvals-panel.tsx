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

  // Drop selections for threads that are no longer pending.
  useEffect(() => {
    const live = new Set(items.map((i) => i.thread_id));
    setSelected((prev) => new Set(Array.from(prev).filter((id) => live.has(id))));
  }, [items]);

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

  const resolveBatch = async (approved: boolean) => {
    const thread_ids = items
      .map((i) => i.thread_id)
      .filter((id) => selected.has(id));
    if (thread_ids.length === 0) return;
    setBusy(true);
    try {
      await apiPost("/api/v1/skills/approve/batch", { thread_ids, approved });
    } finally {
      setBusy(false);
      setSelected(new Set());
      fetchItems();
      bumpRunsRefresh();
    }
  };

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
            <span className="text-muted-foreground">
              {(item.confidence * 100).toFixed(0)}%
            </span>
          </label>
        ))}
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
