from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from agentmetry.api.routes.auth import router as auth_router
from agentmetry.api.trusted_host import TrustedHostMiddleware

from agentmetry.api.routes.audit import router as audit_router
from agentmetry.api.websocket import ws_manager
from agentmetry.api.ws_bridge import ws_event_bridge
from agentmetry.core.auth import verify_ws_token
from agentmetry.core.bus.audit_exporter import audit_exporter
from agentmetry.core.bus.bridges import outbox_persister
from agentmetry.core.bus.bus import bus
from agentmetry.core.bus.outbox import get_outbox
from agentmetry.core.config import settings
from agentmetry.core.paths import data_dir
from agentmetry.core.extensions import load_extensions
from agentmetry.core.health import get_system_health
from agentmetry.core.version import __version__

logger = logging.getLogger(__name__)

_LOG_DIR = data_dir() / "logs"


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




def _start_forwarders() -> list[asyncio.Task]:
    """One task per network sink, tailing the trail (pilot hardening item 19)."""
    if not (settings.audit_export_enabled and settings.audit_forwarder):
        return []
    from agentmetry.core.audit.forwarder import Forwarder
    from agentmetry.core.audit.sinks import forward_destinations

    tasks = []
    for destination in forward_destinations(settings):
        forwarder = Forwarder(destination, settings.audit_export_path)
        tasks.append(asyncio.create_task(forwarder.run(), name=f"forward-{destination.name}"))
        logger.info("Forwarding the trail to %s from its cursor", destination.name)
    return tasks


def antigravity_watcher_wanted() -> bool:
    """Whether this recorder should tail the developer's Antigravity transcripts.

    It used to start whenever the script existed, so every recorder did it,
    including the dashboard demo, whose trail is supposed to hold seeded events
    only. The watcher reads `~/.gemini/antigravity/brain`, the real one, so a
    demo shown to someone could carry the presenter's actual agent activity, and
    a second recorder doubled every Antigravity call. It now runs only where the
    recorder accepts ingest, and `AGENTMETRY_ANTIGRAVITY_WATCHER=0` turns it off.
    """
    if not settings.audit_ingest_enabled:
        return False
    flag = os.environ.get("AGENTMETRY_ANTIGRAVITY_WATCHER", "").strip().lower()
    return flag not in ("0", "false", "no", "off")


def start_transcript_watcher(watcher_path: Path) -> subprocess.Popen:
    """Start the Antigravity transcript watcher, tied to this process's life.

    Its stdin is a pipe only this process holds, and the lifeline variable
    tells it to exit at end-of-file. When this process dies, however it dies,
    the pipe closes and the watcher follows. Without it each restart left a
    watcher behind, and every one of them recorded every Antigravity call.
    """
    return subprocess.Popen(
        [sys.executable, str(watcher_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "AGENTMETRY_WATCHER_LIFELINE": "1"},
    )


def stop_transcript_watcher(process: subprocess.Popen) -> None:
    """Close the lifeline, then terminate. Closing alone is enough; terminate is
    for a watcher that predates the lifeline."""
    try:
        if process.stdin:
            process.stdin.close()
    except OSError:
        pass
    process.terminate()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from agentmetry.core.audit.migrate import backfill_db_from_jsonl

    # The ingest-only token, which hooks prefer and the ingest route accepts.
    # Without it a hook running as another account (Codex's Windows sandbox)
    # could not authenticate and every event it sent was lost (#302). Owner-
    # only like the full token; `hooks install` widens it to Codex's sandbox
    # accounts where they exist. A failure here costs that, never the boot.
    from agentmetry.core import api_token
    from agentmetry.core.auth import auth_is_disabled

    if not auth_is_disabled():
        try:
            api_token.ensure_ingest_token()
        except OSError:
            logger.exception("Could not write the ingest-only token; hooks fall back to the full token")

    # Backfill SQLite from the existing JSONL trail. A broken or locked audit DB
    # must degrade the dashboard, never stop the daemon from booting: the
    # recorder's job is to keep recording.
    try:
        await asyncio.to_thread(backfill_db_from_jsonl)
    except Exception:
        logger.exception("Audit trail backfill failed; continuing without it")

    # Replay events the hooks captured while this process was down. Same
    # non-fatal contract as the backfill: a broken spool must not stop the
    # recorder from booting.
    #
    # Deliberately not awaited. Draining a few thousand spooled events takes
    # minutes, and awaiting it here holds the ingest port closed for the whole
    # time — so every hook that fires during the drain is refused and spooled,
    # which makes the next drain larger. The recorder has to be reachable first
    # and catch up second.
    from agentmetry.core.audit.heartbeat import heartbeat_forever
    from agentmetry.core.audit.spool import drain_forever, drain_spool

    async def _boot_drain() -> None:
        try:
            await drain_spool()
        except Exception:
            logger.exception("Hook spool drain failed; continuing without it")

    # Bring the triage index back in step with the trail. `reconcile_at_boot`
    # declines rather than rebuilding when the trail cannot account for a
    # decision the index already holds — a pruned or repointed trail must not
    # silently erase the corrective-action record.
    from agentmetry.core.audit.detection.disposition import reconcile_at_boot

    try:
        await asyncio.to_thread(reconcile_at_boot)
    except Exception:
        logger.exception("Disposition reconcile failed; continuing without it")

    # Event bus first: everything downstream publishes onto it.
    bus.set_initial_seq(get_outbox().max_seq())
    bridge_tasks = [
        asyncio.create_task(ws_event_bridge(), name="ws-bridge"),
        asyncio.create_task(outbox_persister(), name="outbox-persister"),
        asyncio.create_task(audit_exporter(), name="audit-exporter"),
        asyncio.create_task(_boot_drain(), name="spool-boot-drain"),
        # Keep draining for as long as we run. A boot-only drain leaves a
        # backlog growing unnoticed whenever ingest is unreachable while the
        # process itself stays up.
        asyncio.create_task(drain_forever(), name="spool-drain"),
        # Attest on an interval so a machine that goes quiet is distinguishable
        # from a machine whose hooks were removed. Absence only means something
        # if presence was being asserted.
        asyncio.create_task(heartbeat_forever(), name="heartbeat"),
    ]
    bridge_tasks += _start_forwarders()

    # The removed agent runtime's MCP driver host. Off unless
    # AGENTMETRY_LEGACY_DRIVERS=1 (#209): it spawned tools/vault_fs_server.py on
    # every boot of a recorder that has no use for it.
    mount_task = None
    if settings.legacy_drivers:
        from agentmetry.core.drivers.host import get_mcp_host

        # Mount in the background: a slow npx download must not delay boot.
        mount_task = asyncio.create_task(get_mcp_host().mount_all(), name="driver-mounts")

    # Create the per-install API token now, before the first hook asks for it.
    from agentmetry.core.auth import effective_key

    try:
        if effective_key():
            logger.info("API authentication on; local clients read the token from the data directory")
        else:
            logger.warning("API authentication is OFF (AGENTMETRY_AUTH_DISABLED); development only")
    except OSError as exc:
        logger.error("Could not create the API token (%s); every request will be refused", exc)

    # Opt-in (AGENTMETRY_AUTO_INSTALL_HOOKS=1). Unconditional, this rewrote the
    # developer's global IDE hook configs to point at whichever checkout booted,
    # which is how a test clone or demo instance took over live hooks.
    if settings.auto_install_hooks:
        from agentmetry.core.audit.hook_bootstrap import bootstrap_tier_b_hooks

        try:
            hook_paths = bootstrap_tier_b_hooks()
            if hook_paths.get("cursor"):
                logger.info("Global Cursor hooks ready: %s", hook_paths["cursor"])
            if hook_paths.get("claude"):
                logger.info("Global Claude hooks ready: %s", hook_paths["claude"])
        except Exception as exc:
            logger.warning("Tier B hook bootstrap failed: %s", exc)
    else:
        logger.info(
            "IDE hooks are not rewritten at boot. Install or repair them with "
            "`agentmetry hooks install`, or set AGENTMETRY_AUTO_INSTALL_HOOKS=1."
        )

    # Launch transcript watcher for Antigravity in the background
    watcher_process = None
    try:
        watcher_path = Path(__file__).resolve().parents[4] / "scripts" / "antigravity_transcript_watcher.py"
        if watcher_path.exists() and antigravity_watcher_wanted():
            watcher_process = start_transcript_watcher(watcher_path)
            logger.info("Started Antigravity transcript watcher (PID: %s)", watcher_process.pid)
    except Exception as exc:
        logger.warning("Failed to start Antigravity transcript watcher: %s", exc)

    yield
    if mount_task is not None:
        from agentmetry.core.drivers.host import get_mcp_host

        mount_task.cancel()
        await get_mcp_host().unmount_all()
    for task in bridge_tasks:
        task.cancel()
    if watcher_process:
        stop_transcript_watcher(watcher_process)


app = FastAPI(
    title="Agentmetry",
    description="Open-source SIEM flight recorder for AI agent tool-use",
    version=__version__,
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
# Outermost, so a request with a foreign Host header is refused before CORS or
# any route sees it (DNS rebinding; pilot hardening item 9).
app.add_middleware(TrustedHostMiddleware)

app.include_router(audit_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")

load_extensions(app, settings=settings)


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


#: A source checkout's build, which a developer rebuilds and expects to see.
_CHECKOUT_DASHBOARD_DIR = Path(__file__).resolve().parents[3] / "dashboard" / "out"
#: The same export, bundled inside the wheel by the release build. Until 0.10.1
#: nothing put it there, so `pip install agentmetry`, `agentmetry dashboard`
#: signed the browser in and landed it on a JSON 404.
_PACKAGED_DASHBOARD_DIR = Path(__file__).resolve().parents[1] / "dashboard_static"

_DASHBOARD_MISSING_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Agentmetry</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{font:16px/1.6 system-ui,sans-serif;max-width:40rem;margin:4rem auto;padding:0 1rem}
code{background:#f2f2f2;padding:.1em .3em;border-radius:3px}</style></head>
<body><h1>Agentmetry is recording.</h1>
<p>The dashboard is not part of this install. Packages from 0.10.1 include it:
<code>pip install --upgrade agentmetry</code>, then restart the recorder.</p>
<p>Recording, detection and the trail do not depend on it. From a shell:
<code>agentmetry stats</code>, <code>agentmetry replay &lt;session&gt;</code>,
<code>agentmetry verify --trail</code>.</p></body></html>"""


def dashboard_dir() -> Path | None:
    """Where the dashboard export is: a checkout's build first, then the package's."""
    for candidate in (_CHECKOUT_DASHBOARD_DIR, _PACKAGED_DASHBOARD_DIR):
        if (candidate / "index.html").is_file():
            return candidate
    return None


def mount_dashboard(target: FastAPI, directory: Path | None = None) -> bool:
    """Serve the dashboard's static export when there is one.

    Single-process mode: the orchestrator serves the export at the root,
    mounted last so it only catches paths not already claimed by the API or
    WebSocket. Dev uses the :3000 dev server instead. With no export, the root
    serves a page saying so, because the sign-in link redirects there and a
    JSON 404 reads as a broken product.
    """
    if directory is None:
        directory = dashboard_dir()
    if directory is None or not directory.is_dir():
        logger.info(
            "Dashboard export not found (looked in %s and %s); serving a notice at /",
            _CHECKOUT_DASHBOARD_DIR,
            _PACKAGED_DASHBOARD_DIR,
        )
        from fastapi.responses import HTMLResponse

        @target.get("/", include_in_schema=False, name="dashboard-missing")
        async def dashboard_missing() -> HTMLResponse:
            return HTMLResponse(_DASHBOARD_MISSING_PAGE, headers={"Cache-Control": "no-cache"})

        return False

    from fastapi.staticfiles import StaticFiles

    class DashboardFiles(StaticFiles):
        """The export, with its HTML pages marked `no-cache`.

        Served with no cache header at all, a browser may reuse a stale page on
        an ordinary reload, and the page names the old scripts, so an upgraded
        recorder kept showing the previous dashboard until a hard reload.
        `no-cache` still lets the browser keep a copy; it only has to ask
        whether the page changed. The scripts are not touched: their names
        change with every build.
        """

        async def get_response(self, path: str, scope):  # type: ignore[override]
            response = await super().get_response(path, scope)
            if response.headers.get("content-type", "").startswith("text/html"):
                response.headers["Cache-Control"] = "no-cache"
            return response

    target.mount("/", DashboardFiles(directory=str(directory), html=True), name="dashboard")
    logger.info("Serving dashboard from %s", directory)
    return True


mount_dashboard(app)
