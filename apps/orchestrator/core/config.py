from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    vault_path: Path = Path(__file__).resolve().parents[3] / "vault"
    qdrant_url: str = "http://localhost:6333"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    embedding_model: str = "nomic-embed-text"
    collection_name: str = "agent_memory"
    database_url: str = "sqlite+aiosqlite:///./data/telemetry.db"
    approval_threshold: float = 0.9
    cost_alert_threshold: float = 1.0

    class Config:
        env_prefix = "BLACKBOX_"
        env_file = ".env"


settings = Settings()
