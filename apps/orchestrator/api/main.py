from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import Depends, FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from api.routes.audit import router as audit_router
from api.websocket import ws_manager
from api.ws_bridge import ws_event_bridge
from core.auth import require_api_key, verify_ws_token
from core.bus.audit_exporter import audit_exporter
from core.bus.bridges import outbox_persister, trigger_bridge
from core.bus.bus import bus
from core.bus.outbox import get_outbox
from core.config import settings
from core.health import get_system_health

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




@asynccontextmanager
async def lifespan(app: FastAPI):
    # Event bus first: everything downstream publishes onto it.
    bus.set_initial_seq(get_outbox().max_seq())
    bridge_tasks = [
        asyncio.create_task(ws_event_bridge(), name="ws-bridge"),
        asyncio.create_task(outbox_persister(), name="outbox-persister"),
        asyncio.create_task(audit_exporter(), name="audit-exporter"),
        asyncio.create_task(trigger_bridge(), name="trigger-bridge"),
    ]

    # Drivers mount in the background: a slow npx download must not delay boot.
    from core.drivers.host import get_mcp_host

    mount_task = asyncio.create_task(get_mcp_host().mount_all(), name="driver-mounts")

    from core.audit.hook_bootstrap import bootstrap_tier_b_hooks

    try:
        hook_paths = bootstrap_tier_b_hooks()
        if hook_paths.get("cursor"):
            logger.info("Global Cursor hooks ready: %s", hook_paths["cursor"])
        if hook_paths.get("claude"):
            logger.info("Global Claude hooks ready: %s", hook_paths["claude"])
    except Exception as exc:
        logger.warning("Tier B hook bootstrap failed: %s", exc)

    # Launch transcript watcher for Antigravity in the background
    import subprocess
    import sys
    watcher_process = None
    try:
        watcher_path = Path(__file__).resolve().parents[3] / "scripts" / "antigravity_transcript_watcher.py"
        if watcher_path.exists():
            watcher_process = subprocess.Popen(
                [sys.executable, str(watcher_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info("Started Antigravity transcript watcher (PID: %s)", watcher_process.pid)
    except Exception as exc:
        logger.warning("Failed to start Antigravity transcript watcher: %s", exc)

    yield
    mount_task.cancel()
    await get_mcp_host().unmount_all()
    for task in bridge_tasks:
        task.cancel()
    if watcher_process:
        watcher_process.terminate()


app = FastAPI(
    title="AgentAudit",
    description="Local flight recorder for governed AI agent tool-use",
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

app.include_router(audit_router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health():
    return await get_system_health()





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
