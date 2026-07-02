"use client";

import { useEffect, useState } from "react";
import { FileText, Folder } from "lucide-react";
import { ORCHESTRATOR_URL } from "@/lib/utils";
import { useAgentStore } from "@/lib/store";

interface VaultEntry {
  type: "folder" | "file";
  path: string;
  name: string;
  folder?: string;
}

interface NotePreview {
  path: string;
  preview: string;
  meta: Record<string, unknown>;
}

export function MemoryNavigator() {
  const incrementMemoryAccess = useAgentStore((s) => s.incrementMemoryAccess);
  const [entries, setEntries] = useState<VaultEntry[]>([]);
  const [selected, setSelected] = useState<NotePreview | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({
    "10-Knowledge": true,
    "00-Inbox": true,
    "99-Relations": true,
  });

  useEffect(() => {
    fetch(`${ORCHESTRATOR_URL}/api/v1/vault/tree`)
      .then((r) => r.json())
      .then((data) => setEntries(data.entries || []))
      .catch(() => setEntries([]));
  }, []);

  const folders = entries.filter((e) => e.type === "folder");

  const loadNote = async (path: string) => {
    incrementMemoryAccess(path);
    try {
      const res = await fetch(`${ORCHESTRATOR_URL}/api/v1/vault/notes/${path}`);
      if (res.ok) {
        setSelected(await res.json());
      }
    } catch {
      setSelected(null);
    }
  };

  return (
    <div>
      <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
        Memory Navigator
      </h2>
      <div className="text-xs text-muted-foreground space-y-0.5 font-mono max-h-48 overflow-y-auto">
        {folders.map((folder) => {
          const files = entries.filter(
            (e) => e.type === "file" && e.folder === folder.path
          );
          const isOpen = expanded[folder.path] ?? false;

          return (
            <div key={folder.path}>
              <button
                type="button"
                className="flex items-center gap-1 w-full hover:text-foreground py-0.5"
                onClick={() =>
                  setExpanded((prev) => ({ ...prev, [folder.path]: !isOpen }))
                }
              >
                <Folder className="h-3 w-3 shrink-0" />
                {folder.name}/
              </button>
              {isOpen &&
                files.map((file) => (
                  <button
                    key={file.path}
                    type="button"
                    className={`flex items-center gap-1 w-full pl-4 py-0.5 truncate hover:text-foreground text-left ${
                      selected?.path === file.path ? "text-primary" : ""
                    }`}
                    onClick={() => loadNote(file.path)}
                  >
                    <FileText className="h-3 w-3 shrink-0" />
                    {file.name}
                  </button>
                ))}
            </div>
          );
        })}
      </div>

      {selected && (
        <div className="mt-3 p-2 rounded-md border border-border bg-muted/30 text-xs">
          <div className="font-mono text-primary mb-1 truncate">{selected.path}</div>
          <pre className="whitespace-pre-wrap text-muted-foreground max-h-32 overflow-y-auto">
            {selected.preview}
          </pre>
        </div>
      )}
    </div>
  );
}
