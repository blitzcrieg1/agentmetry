"use client";

import { useState } from "react";
import { useAgentStore } from "@/lib/store";
import { ORCHESTRATOR_URL } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function ApprovalModal() {
  const executionStatus = useAgentStore((s) => s.executionStatus);
  const approvalDraft = useAgentStore((s) => s.approvalDraft);
  const approvalConfidence = useAgentStore((s) => s.approvalConfidence);
  const threadId = useAgentStore((s) => s.threadId);
  const setExecutionStatus = useAgentStore((s) => s.setExecutionStatus);
  const clearApproval = useAgentStore((s) => s.clearApproval);
  const updateNode = useAgentStore((s) => s.updateNode);
  const appendTerminal = useAgentStore((s) => s.appendTerminal);

  const [editedDraft, setEditedDraft] = useState("");
  const [isModifying, setIsModifying] = useState(false);

  if (executionStatus !== "waiting_for_input") return null;

  const draft = isModifying ? editedDraft : approvalDraft;

  const sendApproval = async (approved: boolean, modified?: string) => {
    if (!threadId) return;

    try {
      const res = await fetch(`${ORCHESTRATOR_URL}/api/v1/skills/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          thread_id: threadId,
          approved,
          modified_input: modified || null,
        }),
      });
      const data = await res.json();

      if (data.status === "approved") {
        updateNode("human_approval", "completed");
        updateNode("finalize", "completed");
        setExecutionStatus("completed");
        appendTerminal("✓ Approved and finalized");
      } else if (data.status === "terminated") {
        setExecutionStatus("failed");
        appendTerminal("✗ Thread terminated");
      }
      clearApproval();
    } catch (err) {
      appendTerminal(`Approval error: ${err}`);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <Card className="w-full max-w-2xl mx-4 border-amber-500/50 shadow-2xl shadow-amber-500/10">
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            Human Approval Required
            <span className="text-sm font-normal text-amber-400">
              Confidence: {(approvalConfidence * 100).toFixed(0)}%
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {isModifying ? (
            <textarea
              className="w-full h-48 rounded-md border border-border bg-muted p-3 text-sm font-mono resize-none focus:outline-none focus:ring-2 focus:ring-primary"
              value={editedDraft}
              onChange={(e) => setEditedDraft(e.target.value)}
            />
          ) : (
            <pre className="w-full h-48 rounded-md border border-border bg-muted p-3 text-sm font-mono overflow-auto whitespace-pre-wrap">
              {approvalDraft}
            </pre>
          )}

          <div className="flex gap-2 justify-end">
            <Button variant="destructive" onClick={() => sendApproval(false)}>
              Terminate
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                if (isModifying) {
                  sendApproval(true, editedDraft);
                } else {
                  setEditedDraft(approvalDraft);
                  setIsModifying(true);
                }
              }}
            >
              {isModifying ? "Approve Modified" : "Modify Input"}
            </Button>
            <Button onClick={() => sendApproval(true)}>
              Approve & Continue
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
