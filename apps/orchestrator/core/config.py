from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ORCHESTRATOR_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime configuration for the Agentmetry SIEM flight recorder."""

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

    detection_rules_path: Path = (
        _ORCHESTRATOR_ROOT.parent.parent / "policies" / "detection" / "manifest.yaml"
    )

    # Demo MCP vault — doctor, drivers.json, vault_fs server (not a skill runtime).
    vault_path: Path = Path(__file__).resolve().parents[3] / "vault"


settings = Settings()
