"use client";

import { useEffect, useState } from "react";
import { ORCHESTRATOR_URL } from "@/lib/utils";
import { apiPost } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface ServiceStatus {
  status: "up" | "down" | "skipped";
  detail?: string;
  fallback?: string;
  backend?: string;
  model_ready?: boolean;
  indexed?: boolean;
  notes?: number;
}

interface HealthResponse {
  status: string;
  vault: ServiceStatus & { path?: string };
  qdrant: ServiceStatus & { url?: string };
  ollama: ServiceStatus & { url?: string; model?: string };
  gemini?: ServiceStatus & { model?: string; provider?: string };
  llm_provider?: string;
  postgres?: ServiceStatus;
  modes: {
    rag: string;
    llm: string;
    telemetry?: string;
    context_window_tokens?: number;
  };
}

export function ServiceStatusPanel() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [adminMsg, setAdminMsg] = useState<string | null>(null);
  const [adminBusy, setAdminBusy] = useState(false);

  const fetchHealth = () => {
    fetch(`${ORCHESTRATOR_URL}/api/v1/health`)
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setHealth(null));
  };

  useEffect(() => {
    fetchHealth();
    const interval = setInterval(fetchHealth, 30000);
    return () => clearInterval(interval);
  }, []);

  const runAdmin = async (action: "reload" | "reindex") => {
    setAdminBusy(true);
    setAdminMsg(null);
    try {
      if (action === "reload") {
        const data = await apiPost("/api/v1/skills/reload");
        setAdminMsg(`Reloaded ${data.registered?.length ?? 0} skills`);
      } else {
        const data = await apiPost("/api/v1/vault/reindex");
        setAdminMsg(`Indexed ${data.indexed_chunks ?? 0} chunks`);
      }
      fetchHealth();
    } catch (err) {
      setAdminMsg(String(err));
    } finally {
      setAdminBusy(false);
    }
  };

  const overall = health?.status ?? "unknown";

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center justify-between">
          System Status
          <span
            className={`text-xs font-normal capitalize ${
              overall === "ok"
                ? "text-green-400"
                : overall === "degraded"
                  ? "text-amber-400"
                  : "text-red-400"
            }`}
          >
            {overall}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <ServiceRow
          label="Vault"
          status={health?.vault.status}
          detail={
            health?.vault.notes != null
              ? `${health.vault.notes} notes`
              : health?.vault.detail
          }
        />
        <ServiceRow
          label="Qdrant"
          status={health?.qdrant.status}
          detail={
            health?.qdrant.status === "up"
              ? health.qdrant.indexed
                ? "indexed"
                : "empty"
              : health?.qdrant.fallback
          }
        />
        <ServiceRow
          label="Gemini"
          status={health?.gemini?.status}
          detail={
            health?.gemini?.status === "up"
              ? health.gemini.model
              : health?.gemini?.fallback ?? health?.gemini?.detail
          }
        />
        {health?.llm_provider !== "gemini" && (
          <ServiceRow
            label="Ollama"
            status={health?.ollama.status}
            detail={
              health?.ollama.status === "up"
                ? health.ollama.model_ready
                  ? health.ollama.model
                  : "model not pulled"
                : health?.ollama.fallback
            }
          />
        )}
        {health?.postgres && health.postgres.status !== "skipped" && (
          <ServiceRow
            label="Postgres"
            status={health.postgres.status === "up" ? "up" : "down"}
            detail={
              health.postgres.status === "up"
                ? health.postgres.backend
                : health.postgres.fallback
            }
          />
        )}
        {health?.modes && (
          <div className="pt-2 border-t border-border text-xs text-muted-foreground space-y-1">
            <div>RAG: {health.modes.rag.replace(/_/g, " ")}</div>
            <div>LLM: {health.modes.llm.replace(/_/g, " ")}</div>
            {health.modes.telemetry && (
              <div>Telemetry: {health.modes.telemetry}</div>
            )}
          </div>
        )}
        <div className="pt-2 border-t border-border space-y-2">
          <p className="text-xs text-muted-foreground">Admin</p>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="outline"
              className="flex-1 text-xs"
              disabled={adminBusy}
              onClick={() => runAdmin("reload")}
            >
              Reload Skills
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="flex-1 text-xs"
              disabled={adminBusy}
              onClick={() => runAdmin("reindex")}
            >
              Reindex Vault
            </Button>
          </div>
          {adminMsg && (
            <p className="text-xs text-muted-foreground font-mono truncate">{adminMsg}</p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function ServiceRow({
  label,
  status,
  detail,
}: {
  label: string;
  status?: string;
  detail?: string;
}) {
  const up = status === "up";
  return (
    <div className="flex items-center justify-between text-sm">
      <div className="flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${up ? "bg-green-500" : "bg-red-500"}`} />
        <span className="text-muted-foreground">{label}</span>
      </div>
      <span className="text-xs font-mono text-muted-foreground truncate max-w-[120px]">
        {detail ?? (up ? "up" : "down")}
      </span>
    </div>
  );
}
