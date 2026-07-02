"use client";

import { useEffect, useRef } from "react";
import { useAgentStore } from "@/lib/store";
import { WS_URL } from "@/lib/utils";
import { buildGraphNodes } from "@/lib/graph-utils";

function wsUrl(sessionId: string): string {
  const base = `${WS_URL}/ws/${sessionId}`;
  const apiKey = process.env.NEXT_PUBLIC_BLACKBOX_API_KEY;
  if (apiKey) {
    return `${base}?token=${encodeURIComponent(apiKey)}`;
  }
  return base;
}

export function useWebSocket() {
  const sessionId = useAgentStore((s) => s.sessionId);
  const setWsConnected = useAgentStore((s) => s.setWsConnected);
  const appendTerminal = useAgentStore((s) => s.appendTerminal);
  const updateNode = useAgentStore((s) => s.updateNode);
  const setExecutionStatus = useAgentStore((s) => s.setExecutionStatus);
  const setThreadId = useAgentStore((s) => s.setThreadId);
  const setApproval = useAgentStore((s) => s.setApproval);
  const updateMetrics = useAgentStore((s) => s.updateMetrics);
  const setGraphNodes = useAgentStore((s) => s.setGraphNodes);
  const appendStreamToken = useAgentStore((s) => s.appendStreamToken);
  const incrementMemoryAccess = useAgentStore((s) => s.incrementMemoryAccess);
  const wsRef = useRef<WebSocket | null>(null);

  const applyMetrics = (metrics: Record<string, number>) => {
    if (!metrics) return;
    const inputTokens = metrics.input_tokens ?? metrics.inputTokens ?? 0;
    const outputTokens = metrics.output_tokens ?? metrics.outputTokens ?? 0;
    updateMetrics({
      cost: metrics.cost ?? 0,
      inputTokens,
      outputTokens,
      contextUsagePercent: Math.min(
        Math.round((inputTokens / 1_048_576) * 100),
        100
      ),
    });
  };

  useEffect(() => {
    const ws = new WebSocket(wsUrl(sessionId));
    wsRef.current = ws;

    ws.onopen = () => setWsConnected(true);
    ws.onclose = () => setWsConnected(false);

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      switch (data.type) {
        case "execution_started":
          setThreadId(data.thread_id);
          setExecutionStatus("running");
          if (data.nodes?.length) {
            setGraphNodes(buildGraphNodes(data.nodes));
          }
          appendTerminal(`▶ Execution started: ${data.skill}`);
          if (data.context_sources) {
            for (const src of data.context_sources) {
              incrementMemoryAccess(src);
            }
            appendTerminal(`Context loaded: ${data.context_sources.length} notes`);
          }
          break;

        case "node_update":
          updateNode(data.node, data.status, data.output);
          if (data.metrics) applyMetrics(data.metrics);
          break;

        case "token":
          appendStreamToken(data.node, data.token);
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
          if (data.metrics) applyMetrics(data.metrics);
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

        case "cost_alert":
          appendTerminal(
            `⚠ Cost alert: $${data.cost.toFixed(4)} exceeds threshold $${data.threshold.toFixed(2)}`
          );
          break;

        case "drift_alert":
          appendTerminal(`⚠ Drift detected: ${data.message}`);
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
    setGraphNodes,
    appendStreamToken,
    incrementMemoryAccess,
  ]);

  return wsRef;
}
