"use client";

import { useEffect, useRef } from "react";
import { useAgentStore } from "@/lib/store";
import { WS_URL } from "@/lib/utils";

export function useWebSocket() {
  const sessionId = useAgentStore((s) => s.sessionId);
  const setWsConnected = useAgentStore((s) => s.setWsConnected);
  const appendTerminal = useAgentStore((s) => s.appendTerminal);
  const updateNode = useAgentStore((s) => s.updateNode);
  const setExecutionStatus = useAgentStore((s) => s.setExecutionStatus);
  const setThreadId = useAgentStore((s) => s.setThreadId);
  const setApproval = useAgentStore((s) => s.setApproval);
  const updateMetrics = useAgentStore((s) => s.updateMetrics);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const ws = new WebSocket(`${WS_URL}/ws/${sessionId}`);
    wsRef.current = ws;

    ws.onopen = () => setWsConnected(true);
    ws.onclose = () => setWsConnected(false);

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      switch (data.type) {
        case "execution_started":
          setThreadId(data.thread_id);
          setExecutionStatus("running");
          appendTerminal(`▶ Execution started: ${data.skill}`);
          break;

        case "node_update":
          updateNode(data.node, data.status, data.output);
          if (data.output) appendTerminal(`[${data.node}] ${data.output}`);
          break;

        case "token":
          appendTerminal(data.token);
          break;

        case "approval_required":
          setExecutionStatus("waiting_for_input");
          setApproval(data.draft, data.confidence);
          updateNode("human_approval", "waiting");
          updateNode("critic", "completed");
          appendTerminal(
            `⚠ Approval required (confidence: ${(data.confidence * 100).toFixed(0)}%)`
          );
          break;

        case "execution_completed":
          setExecutionStatus("completed");
          updateNode("finalize", "completed");
          if (data.metrics) {
            updateMetrics({
              cost: data.metrics.cost,
              inputTokens: data.metrics.input_tokens,
              outputTokens: data.metrics.output_tokens,
              latencyMs: data.metrics.latency_ms,
            });
          }
          appendTerminal(`✓ Completed — archived to ${data.archive_path}`);
          break;

        case "execution_failed":
          setExecutionStatus("failed");
          appendTerminal(`✗ Failed: ${data.error}`);
          break;

        case "execution_terminated":
          setExecutionStatus("failed");
          appendTerminal("✗ Terminated by user");
          break;
      }
    };

    return () => {
      ws.close();
    };
  }, [
    sessionId,
    setWsConnected,
    appendTerminal,
    updateNode,
    setExecutionStatus,
    setThreadId,
    setApproval,
    updateMetrics,
  ]);

  return wsRef;
}
