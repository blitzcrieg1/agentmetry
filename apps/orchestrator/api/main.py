from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from api.routes.skills import router as skills_router
from api.websocket import ws_manager
from core.config import settings
from core.memory.vault_watcher import VaultWatcher
from core.telemetry.store import TelemetryStore

vault_watcher: VaultWatcher | None = None
telemetry = TelemetryStore()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global vault_watcher
    vault_watcher = VaultWatcher()
    try:
        await vault_watcher.start()
    except Exception:
        pass  # Vault watcher optional if Qdrant unavailable
    yield
    if vault_watcher:
        vault_watcher.stop()


app = FastAPI(
    title="BLACKBOX Agentic OS",
    description="Obsidian-Cortex State Machine Execution Environment",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(skills_router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health():
    return {
        "status": "ok",
        "vault": str(settings.vault_path),
        "qdrant": settings.qdrant_url,
    }


@app.get("/api/v1/telemetry")
async def get_telemetry():
    return telemetry.get_stats()


@app.post("/api/v1/vault/reindex")
async def reindex_vault():
    from core.memory.rag_engine import RAGEngine

    engine = RAGEngine()
    count = await engine.index_vault()
    return {"indexed_chunks": count}


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await ws_manager.connect(websocket, session_id)
    try:
        while True:
            data = await websocket.receive_text()
            await ws_manager.broadcast(session_id, {
                "type": "echo",
                "data": data,
            })
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, session_id)
