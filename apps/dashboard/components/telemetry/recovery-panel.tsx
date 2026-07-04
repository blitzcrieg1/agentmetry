"use client";

import { useCallback, useEffect, useState } from "react";
import { useAgentStore } from "@/lib/store";
import { ORCHESTRATOR_URL } from "@/lib/utils";
import { apiPost } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface RecoveryItem {
  path: string;
  thread_id: string;
  skill: string;
  status: string;
  created: string;
  classification: "orphan" | "stale_approval";
}

export function RecoveryPanel() {
  const runsRefreshKey = useAgentStore((s) => s.runsRefreshKey);
  const [items, setItems] = useState<RecoveryItem[]>([]);
  const [busy, setBusy] = useState(false);

  const fetchItems = useCallback(() => {
    fetch(`${ORCHESTRATOR_URL}/api/v1/skills/recovery`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => setItems(data.recovery || []))
      .catch(() => setItems([]));
  }, []);

  useEffect(() => {
    fetchItems();
    const interval = setInterval(fetchItems, 60000);
    return () => clearInterval(interval);
  }, [fetchItems, runsRefreshKey]);

  const resolve = async (path: string, action: "mark_failed" | "dismiss") => {
    setBusy(true);
    try {
      await apiPost("/api/v1/skills/recovery/resolve", { path, action });
    } finally {
      setBusy(false);
      fetchItems();
    }
  };

  if (items.length === 0) return null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">
          Recovery <span className="text-muted-foreground/60">· Gate</span>
          <span className="ml-2 text-xs font-normal text-amber-400">
            {items.length} stale after restart
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-xs">
        {items.map((item) => (
          <div key={item.path} className="space-y-1">
            <div className="flex items-center gap-2 font-mono" title={item.path}>
              <span>{item.classification === "orphan" ? "💥" : "⌛"}</span>
              <span className="truncate flex-1">{item.skill}</span>
              <span className="text-muted-foreground">
                {item.classification.replace("_", " ")}
              </span>
            </div>
            <div className="flex gap-2">
              <button
                className="flex-1 rounded border border-border px-2 py-0.5 hover:bg-muted disabled:opacity-50"
                disabled={busy}
                onClick={() => resolve(item.path, "mark_failed")}
              >
                Mark failed
              </button>
              <button
                className="flex-1 rounded border border-border px-2 py-0.5 hover:bg-muted disabled:opacity-50"
                disabled={busy}
                onClick={() => resolve(item.path, "dismiss")}
              >
                Dismiss
              </button>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
