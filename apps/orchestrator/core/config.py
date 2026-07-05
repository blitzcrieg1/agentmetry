from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ORCHESTRATOR_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BLACKBOX_",
        env_file=_ORCHESTRATOR_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    vault_path: Path = Path(__file__).resolve().parents[3] / "vault"
    qdrant_url: str = "http://localhost:6333"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    embedding_model: str = "nomic-embed-text"
    llm_provider: str = "gemini"  # gemini | ollama | mock
    allow_mock: bool = False  # permit mock fallback when no real provider is available
    gemini_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "BLACKBOX_GEMINI_API_KEY",
        ),
    )
    gemini_model: str = "gemini-2.5-flash-lite"
    gemini_embedding_model: str = "gemini-embedding-2"
    embedding_dimensions: int = 768
    collection_name: str = "agent_memory"
    database_url: str = "sqlite:///./data/telemetry.db"
    postgres_url: str = "postgresql://blackbox:blackbox@localhost:5432/agentic_os"
    use_postgres: bool = False
    approval_threshold: float = 0.9
    cost_alert_threshold: float = 1.0
    api_key: str = ""
    context_window_tokens: int = 1_048_576
    gemini_health_cache_seconds: int = 300
    gemini_health_probe: bool = False
    gemini_embed_min_interval_seconds: float = 0.7
    # Pacing: 60 / RPM. Flash-lite free tier ≈10 RPM → 6s; 2.5-flash ≈5 RPM → 13s.
    gemini_flash_min_interval_seconds: float = 6.5
    gemini_flash_daily_limit: int = 20
    gemini_flash_interactive_reserve: int = 8
    kernel_background_run_limit: int = 2
    sandbox_tier1_allowed: str = "git"  # comma-separated binaries runnable in the jail
    # Telegram channel adapter — ships disabled, like the gmail/search drivers.
    channel_telegram_enabled: bool = False
    telegram_bot_token: str = Field(
        default="",
        validation_alias=AliasChoices(
            "TELEGRAM_BOT_TOKEN",
            "BLACKBOX_TELEGRAM_BOT_TOKEN",
        ),
    )
    telegram_allowed_chat_ids: str = ""  # comma-separated; empty refuses to start
    startup_vault_index: bool = True
    startup_index_skip_unchanged: bool = True


settings = Settings()


def get_database_url() -> str:
    """Return PostgreSQL URL when enabled, otherwise SQLite."""
    if settings.use_postgres:
        return settings.postgres_url
    return settings.database_url
