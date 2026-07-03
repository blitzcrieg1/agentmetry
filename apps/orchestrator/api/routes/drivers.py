"""Driver subsystem API — mounted MCP servers and their tool namespaces."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from core.auth import require_api_key
from core.drivers.host import default_config_path, get_mcp_host

router = APIRouter(prefix="/drivers", tags=["drivers"])


@router.get("/")
async def list_drivers():
    host = get_mcp_host()
    return {
        "drivers": host.snapshot(),
        "tools": host.list_tools(),
    }


@router.post("/remount", dependencies=[Depends(require_api_key)])
async def remount_drivers():
    """Re-read vault/.system/drivers.json and remount everything."""
    host = get_mcp_host()
    await host.unmount_all()
    await host.mount_all(default_config_path())
    return {"drivers": host.snapshot()}
