"use client";

import { useCallback, useEffect, useState } from "react";
import { Check, Mail, Pencil, X } from "lucide-react";
import { useAgentStore } from "@/lib/store";
import { apiPost } from "@/lib/api";
import { Button } from "@/components/ui/button";

export function ApprovalInboxCard() {
  const executionStatus = useAgentStore((s) => s.executionStatus);
  const approvalDraft = useAgentStore((s) => s.approvalDraft);
  const approvalConfidence = useAgentStore((s) => s.approvalConfidence);
  const threadId = useAgentStore((s) => s.threadId);
  const activeSkill = useAgentStore((s) => s.activeSkill);
  const setExecutionStatus = useAgentStore((s) => s.setExecutionStatus);
  const clearApproval = useAgentStore((s) => s.clearApproval);
  const appendTerminal = useAgentStore((s) => s.appendTerminal);
  const bumpRunsRefresh = useAgentStore((s) => s.bumpRunsRefresh);

  const [editedDraft, setEditedDraft] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (executionStatus === "waiting_for_input") {
      setEditedDraft(approvalDraft);
      setIsEditing(false);
    }
  }, [executionStatus, approvalDraft, threadId]);

  const sendApproval = useCallback(
    async (approved: boolean, modified?: string) => {
      if (!threadId || busy) return;
      setBusy(true);
      try {
        const data = await apiPost("/api/v1/skills/approve", {
          thread_id: threadId,
          approved,
          modified_input: modified || null,
        });

        if (data.status === "approved" || data.status === "completed") {
          setExecutionStatus("completed");
          appendTerminal(`✓ Approved — archived to ${data.archive_path ?? "vault"}`);
          bumpRunsRefresh();
        } else if (data.status === "terminated") {
          setExecutionStatus("failed");
          appendTerminal("✗ Thread terminated");
        }
        clearApproval();
        setIsEditing(false);
      } catch (err) {
        appendTerminal(`Approval error: ${err}`);
      } finally {
        setBusy(false);
      }
    },
    [
      threadId,
      busy,
      setExecutionStatus,
      appendTerminal,
      bumpRunsRefresh,
      clearApproval,
    ]
  );

  useEffect(() => {
    if (executionStatus !== "waiting_for_input" || busy) return;

    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "SELECT") return;
      if (isEditing && tag === "TEXTAREA") return;

      if (e.key === "a" && !e.metaKey && !e.ctrlKey && !e.altKey && !e.shiftKey) {
        e.preventDefault();
        void sendApproval(true, isEditing ? editedDraft : undefined);
      } else if (e.key === "r" && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        void sendApproval(false);
      }
    };

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [executionStatus, busy, isEditing, editedDraft, sendApproval]);

  if (executionStatus !== "waiting_for_input") return null;

  const skillLabel = (activeSkill || "draft").replace(/_/g, " ");
  const confidencePct = (approvalConfidence * 100).toFixed(0);
  const confidenceTone =
    approvalConfidence >= 0.85
      ? "border-emerald-500/30 bg-emerald-950/40 text-emerald-300"
      : approvalConfidence >= 0.6
        ? "border-amber-500/30 bg-amber-950/40 text-amber-300"
        : "border-red-500/30 bg-red-950/40 text-red-300";

  return (
    <div className="mx-auto w-full max-w-2xl animate-fade-in-up">
      <div className="overflow-hidden rounded-2xl border border-zinc-800/80 bg-zinc-950/50 shadow-2xl shadow-black/40">
        <div className="flex items-center justify-between border-b border-zinc-800/60 px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-500/15 ring-1 ring-violet-500/25">
              <Mail className="h-5 w-5 text-violet-300" />
            </div>
            <div>
              <p className="text-xs font-medium uppercase tracking-wider text-zinc-500">
                Draft ready
              </p>
              <h2 className="text-lg font-semibold capitalize text-zinc-100">{skillLabel}</h2>
            </div>
          </div>
          <span
            className={`rounded-full border px-3 py-1 text-xs font-medium ${confidenceTone}`}
          >
            {confidencePct}% confidence
          </span>
        </div>

        <div className="px-6 py-5">
          {isEditing ? (
            <textarea
              className="min-h-[220px] w-full resize-none rounded-xl border border-zinc-800 bg-zinc-900/60 p-4 text-sm leading-relaxed text-zinc-100 placeholder:text-zinc-600 focus:border-violet-500/40 focus:outline-none focus:ring-2 focus:ring-violet-500/20"
              value={editedDraft}
              onChange={(e) => setEditedDraft(e.target.value)}
              autoFocus
            />
          ) : (
            <div className="min-h-[220px] rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-4">
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-200">
                {approvalDraft}
              </p>
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-zinc-800/60 bg-zinc-950/30 px-6 py-4">
          <p className="text-[11px] text-zinc-500">
            Press <kbd className="rounded border border-zinc-700 px-1.5 py-0.5 font-mono">a</kbd> to
            approve · <kbd className="rounded border border-zinc-700 px-1.5 py-0.5 font-mono">r</kbd>{" "}
            to reject
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="ghost"
              size="sm"
              className="text-zinc-400 hover:text-red-400"
              disabled={busy}
              onClick={() => sendApproval(false)}
            >
              <X className="mr-1.5 h-4 w-4" />
              Reject
            </Button>
            <Button
              variant="outline"
              size="lg"
              className="border-zinc-700 bg-transparent hover:bg-zinc-900"
              disabled={busy}
              onClick={() => {
                if (isEditing) {
                  setIsEditing(false);
                  setEditedDraft(approvalDraft);
                } else {
                  setEditedDraft(approvalDraft);
                  setIsEditing(true);
                }
              }}
            >
              <Pencil className="mr-1.5 h-4 w-4" />
              {isEditing ? "Cancel edit" : "Edit"}
            </Button>
            <Button
              size="lg"
              className="min-w-[140px] bg-violet-600 hover:bg-violet-500"
              disabled={busy}
              onClick={() =>
                sendApproval(true, isEditing && editedDraft !== approvalDraft ? editedDraft : undefined)
              }
            >
              <Check className="mr-1.5 h-4 w-4" />
              Approve
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
