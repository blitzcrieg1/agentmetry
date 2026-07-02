"""Service health probes for Qdrant, Ollama, and vault."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
from qdrant_client import QdrantClient

from core.config import get_database_url, settings
from core.llm.gemini import check_gemini_health
from core.memory.rag_engine import RAGEngine


async def check_vault() -> dict[str, Any]:
    vault = Path(settings.vault_path)
    if not vault.exists():
        return {"status": "down", "path": str(vault), "detail": "Vault path missing"}
    md_count = len(list(vault.rglob("*.md")))
    return {"status": "up", "path": str(vault), "notes": md_count}


async def check_qdrant() -> dict[str, Any]:
    try:
        client = QdrantClient(
            url=settings.qdrant_url,
            timeout=2,
            check_compatibility=False,
        )
        collections = client.get_collections().collections
        names = [c.name for c in collections]
        indexed = settings.collection_name in names
        return {
            "status": "up",
            "url": settings.qdrant_url,
            "collections": names,
            "indexed": indexed,
        }
    except Exception as exc:
        return {
            "status": "down",
            "url": settings.qdrant_url,
            "fallback": "keyword_search",
            "detail": str(exc)[:120],
        }


async def check_ollama() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{settings.ollama_base_url}/api/tags",
                timeout=2.0,
            )
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}")

            models = [m["name"] for m in resp.json().get("models", [])]
            model_ready = any(settings.ollama_model in m for m in models)
            return {
                "status": "up",
                "url": settings.ollama_base_url,
                "model": settings.ollama_model,
                "model_ready": model_ready,
                "models": models[:5],
            }
    except Exception as exc:
        return {
            "status": "down",
            "url": settings.ollama_base_url,
            "fallback": "mock_llm",
            "detail": str(exc)[:120],
        }


async def check_postgres() -> dict[str, Any]:
    if not settings.use_postgres:
        return {"status": "skipped", "backend": "sqlite", "detail": "PostgreSQL disabled"}

    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(get_database_url(), pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "up", "backend": "postgres", "url": settings.postgres_url.split("@")[-1]}
    except Exception as exc:
        return {
            "status": "down",
            "backend": "postgres",
            "fallback": "sqlite",
            "detail": str(exc)[:120],
        }


async def get_system_health() -> dict[str, Any]:
    vault = await check_vault()
    qdrant = await check_qdrant()
    ollama = await check_ollama()
    gemini = await check_gemini_health()
    postgres = await check_postgres()

    provider = settings.llm_provider.lower()
    if provider == "gemini":
        llm_status = gemini
        llm_mode = "gemini" if gemini["status"] == "up" else gemini.get("fallback", "mock")
    elif provider == "ollama":
        llm_status = ollama
        llm_mode = "ollama" if ollama["status"] == "up" else "mock"
    else:
        llm_status = gemini if gemini["status"] == "up" else ollama
        llm_mode = (
            "gemini" if gemini["status"] == "up"
            else "ollama" if ollama["status"] == "up"
            else "mock"
        )

    services = [vault, qdrant]
    if provider == "gemini" or gemini["status"] == "up":
        services.append(gemini)
    if provider == "ollama":
        services.append(ollama)
    if postgres["status"] != "skipped":
        services.append(postgres)

    memory_chunks = RAGEngine.memory_chunk_count()
    if qdrant["status"] == "up":
        rag_mode = "vector"
    elif memory_chunks > 0 and gemini["status"] == "up":
        rag_mode = "semantic_memory"
    elif memory_chunks > 0:
        rag_mode = "memory"
    else:
        rag_mode = "keyword_fallback"

    core_up = vault["status"] == "up" and (
        gemini["status"] == "up" or ollama["status"] == "up"
    )
    all_up = all(s["status"] == "up" for s in services if s["status"] != "skipped")
    degraded = not all_up and core_up

    return {
        "status": "ok" if core_up else ("degraded" if degraded else "down"),
        "vault": vault,
        "qdrant": qdrant,
        "ollama": ollama,
        "gemini": gemini,
        "llm_provider": provider,
        "postgres": postgres,
        "modes": {
            "rag": rag_mode,
            "llm": llm_mode,
            "telemetry": postgres.get("backend", "sqlite"),
        },
    }
