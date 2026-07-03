from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import Depends, FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from api.routes.events import router as events_router
from api.routes.runs import router as runs_router
from api.routes.skills import router as skills_router
from api.routes.vault import router as vault_router
from api.websocket import ws_manager
from api.ws_bridge import ws_event_bridge
from core.auth import require_api_key, verify_ws_token
from core.bus.bridges import outbox_persister, trigger_bridge
from core.bus.bus import bus
from core.bus.outbox import get_outbox
from core.execution.context import skill_registry
from core.execution.service import recover_interrupts
from core.graphs.checkpointer import init_checkpointer, shutdown_checkpointer
from core.health import get_system_health
from core.kernel.scheduler import get_scheduler
from core.memory.vault_watcher import VaultWatcher
from core.scheduler.engine import start_scheduler, stop_scheduler
from core.telemetry.store import TelemetryStore

logger = logging.getLogger(__name__)

_LOG_DIR = Path(__file__).resolve().parents[1] / "data" / "logs"


def _setup_logging() -> None:
    """Persist app logs to disk so they survive a closed terminal."""
    root = logging.getLogger()
    if any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        return
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    file_handler = RotatingFileHandler(
        _LOG_DIR / "orchestrator.log",
        maxBytes=5_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    if root.level in (logging.NOTSET, logging.WARNING):
        root.setLevel(logging.INFO)


_setup_logging()

vault_watcher: VaultWatcher | None = None
telemetry = TelemetryStore()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global vault_watcher
    # Event bus first: everything downstream publishes onto it.
    bus.set_initial_seq(get_outbox().max_seq())
    bridge_tasks = [
        asyncio.create_task(ws_event_bridge(), name="ws-bridge"),
        asyncio.create_task(outbox_persister(), name="outbox-persister"),
        asyncio.create_task(trigger_bridge(), name="trigger-bridge"),
    ]
    await init_checkpointer()
    skill_registry.reload()
    await recover_interrupts()
    vault_watcher = VaultWatcher()
    try:
        await vault_watcher.start()
    except Exception as exc:
        logger.warning("Vault watcher unavailable: %s", exc)
    try:
        start_scheduler()
    except Exception as exc:
        logger.warning("Scheduler unavailable: %s", exc)
    yield
    stop_scheduler()
    if vault_watcher:
        vault_watcher.stop()
    await get_scheduler().shutdown()
    for task in bridge_tasks:
        task.cancel()
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
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://dashboard:3000",
    ],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(skills_router, prefix="/api/v1")
app.include_router(vault_router, prefix="/api/v1")
app.include_router(runs_router, prefix="/api/v1")
app.include_router(events_router, prefix="/api/v1")


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
    count = await engine.index_vault(force=True)
    return {"indexed_chunks": count}


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    session_id: str,
    token: str | None = Query(None),
):
    if not verify_ws_token(token, websocket):
        await websocket.close(code=4401)
        return
    await ws_manager.connect(websocket, session_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, session_id)


_DASHBOARD_DIR = Path(__file__).resolve().parents[2] / "dashboard" / "out"


def mount_dashboard(target: FastAPI, directory: Path = _DASHBOARD_DIR) -> bool:
    """Serve the dashboard's static export when it has been built.

    Single-process mode: `npm run build` in apps/dashboard emits `out/`, which
    the orchestrator serves at the root. Mounted last so it only catches paths
    not already claimed by the API or WebSocket. Dev uses the :3000 dev server
    instead, so this is a no-op when the export is absent.
    """
    if not directory.is_dir():
        logger.info(
            "Dashboard export not found at %s — run 'npm run build' in "
            "apps/dashboard for single-process serving",
            directory,
        )
        return False

    from fastapi.staticfiles import StaticFiles

    target.mount("/", StaticFiles(directory=str(directory), html=True), name="dashboard")
    logger.info("Serving dashboard from %s", directory)
    return True


mount_dashboard(app)
