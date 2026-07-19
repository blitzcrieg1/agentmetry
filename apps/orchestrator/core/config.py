from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ORCHESTRATOR_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime configuration.

    Two groups, and the split is deliberate. The **SIEM flight recorder** is the
    product: capture, canonical schema, detection, DLP, tool policy, and the
    forward sinks. Everything a security engineer touches lives in that block.

    The **optional governed runtime** below it (Obsidian vault + LangGraph
    skills, Gemini/Ollama, the Telegram/Gmail channel drivers) is a separate,
    off-by-default lineage documented in ``docs/advanced-governed-runtime.md``.
    It is not required for IDE-hook or MCP capture. It is kept, not dead, but a
    cloner evaluating the recorder can ignore it entirely.
    """

    model_config = SettingsConfigDict(
        env_prefix="AGENTMETRY_",
        env_file=_ORCHESTRATOR_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ------------------------------------------------------------------ SIEM
    # Operator identity + optional API key protecting ingest/tail/export.
    operator_id: str = Field(
        default="",
        validation_alias=AliasChoices(
            "OPERATOR_ID",
            "AGENTMETRY_OPERATOR_ID",
        ),
    )
    api_key: str = Field(
        default="",
        validation_alias=AliasChoices("AGENTMETRY_API_KEY"),
    )

    # Canonical JSONL trail + query index (system of record for the hook path).
    audit_export_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "AGENTMETRY_AUDIT_EXPORT_ENABLED",
        ),
    )
    audit_export_path: Path = _ORCHESTRATOR_ROOT / "data" / "audit-forward.jsonl"
    audit_db_path: Path = _ORCHESTRATOR_ROOT / "data" / "audit.db"
    detection_live_db_path: Path = _ORCHESTRATOR_ROOT / "data" / "detection_live.db"
    audit_ingest_enabled: bool = True
    audit_ingest_url: str = "http://127.0.0.1:8000"

    # Forward sinks (all optional; file is the default and never a cloud ledger).
    audit_sink: str = Field(
        default="file",
        validation_alias=AliasChoices("AGENTMETRY_AUDIT_SINK"),
    )
    audit_webhook_url: str = Field(
        default="",
        validation_alias=AliasChoices(
            "AGENTMETRY_AUDIT_WEBHOOK_URL",
        ),
    )
    audit_webhook_timeout_seconds: float = 5.0
    audit_elastic_url: str = Field(
        default="",
        validation_alias=AliasChoices(
            "AGENTMETRY_AUDIT_ELASTIC_URL",
        ),
    )
    audit_elastic_index: str = "logs-agentmetry"
    audit_elastic_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "ELASTIC_API_KEY",
            "AGENTMETRY_ELASTIC_API_KEY",
        ),
    )
    audit_elastic_verify_tls: bool = True
    audit_splunk_hec_url: str = Field(
        default="",
        validation_alias=AliasChoices(
            "AGENTMETRY_AUDIT_SPLUNK_HEC_URL",
        ),
    )
    audit_splunk_hec_token: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SPLUNK_HEC_TOKEN",
            "AGENTMETRY_SPLUNK_HEC_TOKEN",
        ),
    )
    audit_splunk_index: str = "main"
    audit_splunk_sourcetype: str = "agentmetry:json"
    audit_splunk_verify_tls: bool = True
    audit_alert_webhook_url: str = Field(
        default="",
        validation_alias=AliasChoices(
            "AGENTMETRY_AUDIT_ALERT_WEBHOOK_URL",
        ),
    )

    # Semantic DLP — regex scan of tool arguments at the hook boundary.
    dlp_mode: str = Field(
        default="log",
        validation_alias=AliasChoices("AGENTMETRY_DLP_MODE"),
    )
    dlp_rules_path: Path = _ORCHESTRATOR_ROOT.parent.parent / "policies" / "dlp" / "manifest.yaml"
    dlp_pii: bool = True

    # Tool allow/deny policy — enforced at the hook boundary (like DLP block mode).
    tool_policy_mode: str = Field(
        default="log",
        validation_alias=AliasChoices("AGENTMETRY_TOOL_POLICY_MODE"),
    )
    tool_policy_path: Path = (
        _ORCHESTRATOR_ROOT.parent.parent / "policies" / "tool" / "manifest.yaml"
    )

    # Post-ingest policy checks (core/audit/policy.py). Off by default: the
    # built-in ruleset is a hardcoded starting point, and it annotates only, it
    # cannot block. Real prevention lives in the hook (DLP block mode).
    policy_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("AGENTMETRY_POLICY_ENABLED"),
    )
    # off-hours-activity detection. Off by default: "unusual hours" is only a
    # signal once an operator says which hours are usual, and scheduled jobs
    # legitimately run at night.
    detect_off_hours: bool = Field(
        default=False,
        validation_alias=AliasChoices("AGENTMETRY_DETECT_OFF_HOURS"),
    )
    business_hours: str = Field(
        default="09-18",  # local start-end, 24h
        validation_alias=AliasChoices("AGENTMETRY_BUSINESS_HOURS"),
    )
    business_tz: str = Field(
        default="UTC",  # IANA name, e.g. Europe/Athens
        validation_alias=AliasChoices("AGENTMETRY_BUSINESS_TZ"),
    )

    # ------------------------------------ optional governed runtime (advanced)
    # Obsidian vault + LangGraph skills, model providers, and channel drivers.
    # Off by default and not required for SIEM capture. See
    # docs/advanced-governed-runtime.md. Kept for governed-agent demos; a
    # recorder-only deployment can leave this whole block at its defaults.
    vault_path: Path = Path(__file__).resolve().parents[3] / "vault"
    startup_vault_index: bool = True
    startup_index_skip_unchanged: bool = True
    active_loop_archive_days: int = 7
    active_loop_auto_archive: bool = True
    kernel_background_run_limit: int = 2
    sandbox_tier1_allowed: str = "git"  # comma-separated binaries runnable in the jail
    approval_threshold: float = 0.9
    cost_alert_threshold: float = 1.0
    context_window_tokens: int = 1_048_576

    # Model providers (governed runtime only).
    llm_provider: str = "gemini"  # gemini | ollama | mock
    allow_mock: bool = False  # permit mock fallback when no real provider is available
    qdrant_url: str = "http://localhost:6333"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    embedding_model: str = "nomic-embed-text"
    gemini_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
        ),
    )
    gemini_model: str = "gemini-2.5-flash-lite"
    gemini_embedding_model: str = "gemini-embedding-2"
    embedding_dimensions: int = 768
    collection_name: str = "agent_memory"
    gemini_health_cache_seconds: int = 300
    gemini_health_probe: bool = False
    gemini_embed_min_interval_seconds: float = 0.7
    # Pacing: 60 / RPM. Flash-lite free tier ≈10 RPM → 6s; 2.5-flash ≈5 RPM → 13s.
    gemini_flash_min_interval_seconds: float = 6.5
    gemini_flash_daily_limit: int = 20
    gemini_flash_interactive_reserve: int = 8

    # Runtime telemetry store (separate from the audit trail above).
    database_url: str = "sqlite:///./data/telemetry.db"
    postgres_url: str = "postgresql://agentmetry:agentmetry@localhost:5432/agentic_os"
    use_postgres: bool = False

    # Channel drivers — ship disabled, require explicit unlock.
    channel_telegram_enabled: bool = False
    telegram_bot_token: str = Field(
        default="",
        validation_alias=AliasChoices(
            "TELEGRAM_BOT_TOKEN",
        ),
    )
    telegram_allowed_chat_ids: str = ""  # comma-separated; empty refuses to start
    gmail_send_enabled: bool = False  # Phase 4-E — requires explicit unlock


settings = Settings()


def get_database_url() -> str:
    """Return PostgreSQL URL when enabled, otherwise SQLite."""
    if settings.use_postgres:
        return settings.postgres_url
    return settings.database_url
