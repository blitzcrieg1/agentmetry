from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    vault_path: Path = Path(__file__).resolve().parents[3] / "vault"
    qdrant_url: str = "http://localhost:6333"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    embedding_model: str = "nomic-embed-text"
    collection_name: str = "agent_memory"
    database_url: str = "sqlite:///./data/telemetry.db"
    postgres_url: str = "postgresql://blackbox:blackbox@localhost:5432/agentic_os"
    use_postgres: bool = False
    approval_threshold: float = 0.9
    cost_alert_threshold: float = 1.0

    class Config:
        env_prefix = "BLACKBOX_"
        env_file = ".env"


settings = Settings()


def get_database_url() -> str:
    """Return PostgreSQL URL when enabled, otherwise SQLite."""
    if settings.use_postgres:
        return settings.postgres_url
    return settings.database_url
