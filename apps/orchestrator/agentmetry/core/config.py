from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from agentmetry.core.paths import data_dir, env_file

_ORCHESTRATOR_ROOT = Path(__file__).resolve().parents[2]
# Data and .env no longer live beside the package in an installed wheel
# (they were in site-packages). See core/paths.py.
_DATA_DIR = data_dir()
_PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _policy(*parts: str) -> Path:
    """A policy manifest shipped inside the package.

    These are default configuration, not test data: without them DLP, tool
    policy and the YAML detection rules are all inert, and a `pip install` used
    to leave `doctor` opening with three FAILs and secret scanning silently off.

    They live in the package rather than at the repo root because `python -m
    build` builds the wheel from the sdist, and a force-include reaching outside
    the project directory does not survive that trip. Config the package needs
    to run belongs with the package.
    """
    return _PACKAGE_ROOT.joinpath("policies", *parts)


class Settings(BaseSettings):
    """Runtime configuration for the Agentmetry SIEM flight recorder."""

    model_config = SettingsConfigDict(
        env_prefix="AGENTMETRY_",
        env_file=env_file(),
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
    fleet_id: str = Field(
        default="",
        validation_alias=AliasChoices("AGENTMETRY_FLEET_ID"),
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
    audit_export_path: Path = _DATA_DIR / "audit-forward.jsonl"
    audit_db_path: Path = _DATA_DIR / "audit.db"
    detection_live_db_path: Path = _DATA_DIR / "detection_live.db"
    # Triage state. An index over the `detection_disposition` events in the
    # trail, which remain the record — see core/audit/detection/disposition.py.
    detection_disposition_db_path: Path = (
        _DATA_DIR / "detection_disposition.db"
    )
    # Where the trail's anchor log lives, when it is not the sibling default.
    # Anchoring is only worth anything if the log sits somewhere this host
    # cannot rewrite, which in practice means a working copy of a protected
    # remote rather than a path beside the trail. Setting this is how `verify`
    # and `doctor` find that copy without being handed `--anchors` every time,
    # and an operator who has to pass a flag to get the real check is an
    # operator who will end up running the fake one.
    anchor_log_path: str = Field(
        default="",
        validation_alias=AliasChoices("AGENTMETRY_ANCHOR_LOG"),
    )

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
    # `canonical` (default) or `cloudevents`. CloudEvents v1.0 structured mode
    # is what brokers consume; the canonical record still travels whole inside
    # `data`. Default unchanged so an existing webhook keeps receiving the shape
    # it was wired up for.
    audit_webhook_format: str = Field(
        default="canonical",
        validation_alias=AliasChoices("AGENTMETRY_AUDIT_WEBHOOK_FORMAT"),
    )
    # Optional bearer token on every webhook POST. A hosted ingest that binds
    # tenant and host to the token needs this header; an existing webhook that
    # never asked for auth keeps receiving unauthenticated requests, unchanged.
    audit_webhook_token: str = Field(
        default="",
        validation_alias=AliasChoices("AGENTMETRY_AUDIT_WEBHOOK_TOKEN"),
    )
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

    # Google SecOps (Chronicle). Posts UDM directly to `udmevents`, so no CBN
    # parser has to be maintained in the customer's tenant. A service account
    # refreshes; a bearer token expires within the hour and says so at startup.
    audit_chronicle_endpoint: str = Field(
        default="https://malachiteingestion-pa.googleapis.com/v2/udmevents:batchCreate",
        validation_alias=AliasChoices("AGENTMETRY_CHRONICLE_ENDPOINT"),
    )
    audit_chronicle_customer_id: str = Field(
        default="", validation_alias=AliasChoices("AGENTMETRY_CHRONICLE_CUSTOMER_ID")
    )
    audit_chronicle_service_account: str = Field(
        default="", validation_alias=AliasChoices("AGENTMETRY_CHRONICLE_SERVICE_ACCOUNT")
    )
    audit_chronicle_bearer_token: str = Field(
        default="", validation_alias=AliasChoices("AGENTMETRY_CHRONICLE_BEARER_TOKEN")
    )
    audit_chronicle_verify_tls: bool = True
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
    dlp_rules_path: Path = _policy("dlp", "manifest.yaml")
    dlp_pii: bool = True

    # Tool allow/deny policy — enforced at the hook boundary (like DLP block mode).
    tool_policy_mode: str = Field(
        default="log",
        validation_alias=AliasChoices("AGENTMETRY_TOOL_POLICY_MODE"),
    )
    tool_policy_path: Path = (
        _policy("tool", "manifest.yaml")
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
        _policy("detection", "manifest.yaml")
    )

    # The configured MCP servers as an `mcp_inventory` event, for a fleet that
    # wants them in the SIEM (#169). Off by default: the heartbeat names no
    # server, and turning this on is the operator's decision, not ours.
    mcp_inventory_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("AGENTMETRY_MCP_INVENTORY"),
    )

    # Rewrite ~/.claude/settings.json and ~/.cursor/hooks.json on every boot to
    # point at this checkout. Off by default: it used to always run, so booting
    # any second checkout (a test clone, a feature branch, a demo instance)
    # silently repointed the developer's live IDE hooks at it. Hooks are
    # installed on purpose with `agentmetry hooks install`.
    auto_install_hooks: bool = Field(
        default=False,
        validation_alias=AliasChoices("AGENTMETRY_AUTO_INSTALL_HOOKS"),
    )

    # Host names the API answers to besides loopback (comma-separated; `*`
    # disables the check). Everything else gets 400, which is what stops a DNS
    # rebinding page reading the local API. See api/trusted_host.py.
    trusted_hosts: str = Field(
        default="",
        validation_alias=AliasChoices("AGENTMETRY_TRUSTED_HOSTS"),
    )

    # Mount the removed agent runtime's MCP "drivers" (vault/.system/drivers.json,
    # which spawns tools/vault_fs_server.py) at boot. Off by default: the
    # recorder does not need them, and they kept a subprocess and an `mcp<2`
    # pin in every install (#209).
    legacy_drivers: bool = Field(
        default=False,
        validation_alias=AliasChoices("AGENTMETRY_LEGACY_DRIVERS"),
    )

    # Development only: do not create or require the per-install API token.
    # An explicitly set AGENTMETRY_API_KEY is still enforced. `doctor` warns
    # while this is on, and fails if the API is bound beyond loopback.
    # Per-fleet secret for argument hashing (pilot hardening item 11). Unset,
    # tool arguments are fingerprinted with plain SHA-256, which anyone can
    # recompute for a guessable argument (`git status`, a known file path).
    # Set, they are HMAC-SHA256 under this key and `input_redaction` says
    # "hmac": pseudonymised, matchable within the fleet, not reversible by a
    # dictionary without the key. The hooks read the same variable.
    hash_key: str = Field(
        default="",
        repr=False,
        validation_alias=AliasChoices("AGENTMETRY_HASH_KEY"),
    )

    # The trail is the queue (pilot hardening item 19): producers append to it
    # and one task per network sink forwards from a persisted cursor, in
    # batches, retrying with backoff. 0 restores the old inline,
    # one-request-per-event sinks, which drop events while a SIEM is down.
    audit_forwarder: bool = Field(
        default=True,
        validation_alias=AliasChoices("AGENTMETRY_AUDIT_FORWARDER"),
    )

    # Rotate the trail into <stem>.archive/ once the active file reaches this
    # many bytes (pilot hardening item 20, #101). 0 = never. Nothing is ever
    # deleted; see docs/trail-retention.md. 268435456 (256 MiB) is a sensible
    # value for a fleet host.
    trail_rotate_bytes: int = Field(
        default=0,
        validation_alias=AliasChoices("AGENTMETRY_TRAIL_ROTATE_BYTES"),
    )

    # Microsoft Sentinel via the Azure Monitor Logs Ingestion API (pilot
    # hardening item 25). AGENTMETRY_AUDIT_SINK must include `sentinel`.
    # Setup: docs/integrations/sentinel.md.
    audit_sentinel_endpoint: str = Field(default="", validation_alias=AliasChoices("AGENTMETRY_AUDIT_SENTINEL_ENDPOINT"))
    audit_sentinel_dcr_id: str = Field(default="", validation_alias=AliasChoices("AGENTMETRY_AUDIT_SENTINEL_DCR_ID"))
    audit_sentinel_stream: str = Field(
        default="Custom-Agentmetry_CL", validation_alias=AliasChoices("AGENTMETRY_AUDIT_SENTINEL_STREAM")
    )
    audit_sentinel_tenant_id: str = Field(default="", validation_alias=AliasChoices("AGENTMETRY_AUDIT_SENTINEL_TENANT_ID"))
    audit_sentinel_client_id: str = Field(default="", validation_alias=AliasChoices("AGENTMETRY_AUDIT_SENTINEL_CLIENT_ID"))
    audit_sentinel_client_secret: str = Field(
        default="", repr=False, validation_alias=AliasChoices("AGENTMETRY_AUDIT_SENTINEL_CLIENT_SECRET")
    )

    auth_disabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("AGENTMETRY_AUTH_DISABLED"),
    )

    # Demo MCP vault — doctor, drivers.json, vault_fs server (not a skill runtime).
    vault_path: Path = Path(__file__).resolve().parents[4] / "vault"


settings = Settings()
