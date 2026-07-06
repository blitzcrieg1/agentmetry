"use client";

import { useEffect, useRef } from "react";
import { useAgentStore } from "@/lib/store";
import { ORCHESTRATOR_URL, WS_URL } from "@/lib/utils";
import { buildGraphNodes, displayNodesForSkill } from "@/lib/graph-utils";

const PIPELINE_CLEAR_MS = 4500;

function schedulePipelineClear() {
  window.setTimeout(() => {
    useAgentStore.getState().clearPipelineView();
  }, PIPELINE_CLEAR_MS);
}

function wsUrl(sessionId: string): string {
  const base = `${WS_URL}/ws/${sessionId}`;
  const apiKey = process.env.NEXT_PUBLIC_BLACKBOX_API_KEY;
  if (apiKey) {
    return `${base}?token=${encodeURIComponent(apiKey)}`;
  }
  return base;
}

const RECONNECT_DELAY_MS = 3000;

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
  const bumpRunsRefresh = useAgentStore((s) => s.bumpRunsRefresh);
  const wsRef = useRef<WebSocket | null>(null);
  const lastSeqRef = useRef(0);

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
    let disposed = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    const handleEvent = (data: any) => {
      if (typeof data.seq === "number" && data.seq > lastSeqRef.current) {
        lastSeqRef.current = data.seq;
      }

      switch (data.type) {
        case "execution_started":
          setThreadId(data.thread_id);
          setExecutionStatus("running");
          if (data.nodes?.length) {
            setGraphNodes(
              buildGraphNodes(
                displayNodesForSkill({ id: data.skill, nodes: data.nodes })
              )
            );
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

        case "tool_called":
          appendTerminal(`🔧 Tool: ${data.tool}`);
          break;

        case "tool_denied":
          appendTerminal(`⛔ Tool denied: ${data.tool} (${data.reason})`);
          bumpRunsRefresh();
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
          bumpRunsRefresh();
          schedulePipelineClear();
          break;

        case "execution_failed":
          setExecutionStatus("failed");
          appendTerminal(`✗ Failed: ${data.error}`);
          bumpRunsRefresh();
          schedulePipelineClear();
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

    // Reconnect gap-fill: replay everything this session missed from the
    // durable outbox, in order, through the same handler as live frames.
    const replayMissed = async () => {
      if (!lastSeqRef.current) return;
      try {
        const res = await fetch(
          `${ORCHESTRATOR_URL}/api/v1/events/?since=${lastSeqRef.current}&limit=500`
        );
        if (!res.ok) return;
        const data = await res.json();
        for (const event of data.events || []) {
          if (event.session_id === sessionId) {
            handleEvent({ ...event.payload, seq: event.seq });
          } else if (typeof event.seq === "number" && event.seq > lastSeqRef.current) {
            lastSeqRef.current = event.seq;
          }
        }
        appendTerminal("↻ Reconnected — replayed missed events");
      } catch {
        /* orchestrator still down; next reconnect will retry */
      }
    };

    const connect = () => {
      if (disposed) return;
      const ws = new WebSocket(wsUrl(sessionId));
      wsRef.current = ws;

      ws.onopen = () => {
        setWsConnected(true);
        void replayMissed();
      };
      ws.onclose = () => {
        setWsConnected(false);
        if (!disposed) {
          retryTimer = setTimeout(connect, RECONNECT_DELAY_MS);
        }
      };
      ws.onmessage = (event) => handleEvent(JSON.parse(event.data));
    };

    connect();

    return () => {
      disposed = true;
      if (retryTimer) clearTimeout(retryTimer);
      wsRef.current?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    bumpRunsRefresh,
  ]);

  // Global feed: surfaces autonomous runs (vault triggers, cron) and
  // interrupt activity that happens outside this dashboard session.
  useEffect(() => {
    let disposed = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let socket: WebSocket | null = null;

    const connect = () => {
      if (disposed) return;
      const ws = new WebSocket(wsUrl("global"));
      socket = ws;

      ws.onclose = () => {
        if (!disposed) retryTimer = setTimeout(connect, RECONNECT_DELAY_MS);
      };
      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        const origin: string = data.origin_session || "";
        if (!origin.startsWith("autonomous-")) return;

        const rule = origin.replace("autonomous-", "");
        switch (data.type) {
          case "execution_started":
            appendTerminal(`🤖 [${rule}] ${data.skill} started`);
            break;
          case "execution_completed":
            appendTerminal(`🤖 [${rule}] completed — ${data.archive_path}`);
            bumpRunsRefresh();
            break;
          case "execution_failed":
            appendTerminal(`🤖 [${rule}] failed: ${data.error}`);
            bumpRunsRefresh();
            break;
          case "approval_required":
            appendTerminal(`🤖 [${rule}] ⚠ approval required (thread ${data.thread_id})`);
            bumpRunsRefresh();
            break;
          case "interrupt_raised":
            appendTerminal(`⏸ [${rule}] deferred (${data.vector})`);
            bumpRunsRefresh();
            break;
          case "interrupt_resolved":
            appendTerminal(`▶ [${rule}] resuming ${data.skill}`);
            bumpRunsRefresh();
            break;
        }
      };
    };

    connect();

    return () => {
      disposed = true;
      if (retryTimer) clearTimeout(retryTimer);
      socket?.close();
    };
  }, [appendTerminal, bumpRunsRefresh]);

  return wsRef;
}
