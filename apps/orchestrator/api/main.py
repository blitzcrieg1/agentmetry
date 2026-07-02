from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from api.routes.skills import recover_pending_threads, router as skills_router, skill_registry
from api.routes.vault import router as vault_router
from api.websocket import ws_manager
from core.auth import require_api_key
from core.config import settings
from core.graphs.checkpointer import init_checkpointer, shutdown_checkpointer
from core.health import get_system_health
from core.memory.vault_watcher import VaultWatcher
from core.telemetry.store import TelemetryStore

logger = logging.getLogger(__name__)

vault_watcher: VaultWatcher | None = None
telemetry = TelemetryStore()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global vault_watcher
    await init_checkpointer()
    skill_registry.reload()
    await recover_pending_threads()
    vault_watcher = VaultWatcher()
    try:
        await vault_watcher.start()
    except Exception as exc:
        logger.warning("Vault watcher unavailable: %s", exc)
    yield
    if vault_watcher:
        vault_watcher.stop()
    await shutdown_checkpointer()


app = FastAPI(
    title="BLACKBOX Agentic OS",
    description="Obsidian-Cortex State Machine Execution Environment",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://dashboard:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(skills_router, prefix="/api/v1")
app.include_router(vault_router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health():
    return await get_system_health()


@app.get("/api/v1/telemetry")
async def get_telemetry():
    return telemetry.get_stats()


@app.post("/api/v1/vault/reindex", dependencies=[Depends(require_api_key)])
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
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, session_id)
