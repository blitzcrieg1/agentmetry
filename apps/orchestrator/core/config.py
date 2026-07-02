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
    gemini_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "BLACKBOX_GEMINI_API_KEY",
        ),
    )
    gemini_model: str = "gemini-2.5-flash"
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
    gemini_flash_min_interval_seconds: float = 13.0
    startup_vault_index: bool = True
    startup_index_skip_unchanged: bool = True


settings = Settings()


def get_database_url() -> str:
    """Return PostgreSQL URL when enabled, otherwise SQLite."""
    if settings.use_postgres:
        return settings.postgres_url
    return settings.database_url
