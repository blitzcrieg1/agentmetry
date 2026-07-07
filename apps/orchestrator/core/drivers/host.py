"""MCP host — mounts driver servers and routes governed tool calls.

Each driver runs inside its own owner task, which enters the stdio/SSE
context, serves calls, and exits it on shutdown. anyio cancel scopes must be
entered and exited by the same task, so contexts never cross task boundaries.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.bus.bus import bus
from core.bus.events import DRIVER_FAILED, DRIVER_MOUNTED, TOOL_CALLED, TOOL_DENIED
from core.config import settings
from core.drivers.permissions import (
    ToolExecApprovalRequired,
    ToolPermissionError,
    check_tool_allowed,
)
from core.diagnostics.driver_paths import load_resolved_driver_specs
from core.drivers.spec import DriverSpec

logger = logging.getLogger(__name__)

_MOUNT_TIMEOUT_S = 45  # npx may download a package on first mount


@dataclass
class ToolMeta:
    driver: str
    name: str
    qualified: str
    description: str
    tags: list[str] = field(default_factory=list)


@dataclass
class _Driver:
    spec: DriverSpec
    session: Any = None
    task: asyncio.Task | None = None
    shutdown: asyncio.Event = field(default_factory=asyncio.Event)
    state: str = "mounting"  # mounting | mounted | failed | stopped
    error: str = ""
    tools: list[ToolMeta] = field(default_factory=list)


def default_config_path() -> Path:
    return Path(settings.vault_path) / ".system" / "drivers.json"


class MCPHost:
    def __init__(self, interrupt_table: Any = None):
        self._drivers: dict[str, _Driver] = {}
        self._tools: dict[str, ToolMeta] = {}
        self._interrupt_table = interrupt_table

    # ------------------------------------------------------------ lifecycle

    async def mount_all(self, config_path: Path | None = None) -> None:
        for spec in load_resolved_driver_specs(config_path or default_config_path()):
            await self.mount(spec)

    async def mount(self, spec: DriverSpec) -> bool:
        """Start a driver's owner task; returns True once it is serving."""
        driver = _Driver(spec=spec)
        self._drivers[spec.name] = driver
        ready: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        driver.task = asyncio.create_task(
            self._driver_task(driver, ready), name=f"driver-{spec.name}"
        )
        try:
            return await asyncio.wait_for(ready, timeout=_MOUNT_TIMEOUT_S)
        except asyncio.TimeoutError:
            driver.state = "failed"
            driver.error = f"mount timed out after {_MOUNT_TIMEOUT_S}s"
            driver.shutdown.set()
            logger.warning("Driver %s: %s", spec.name, driver.error)
            return False

    async def _driver_task(self, driver: _Driver, ready: asyncio.Future) -> None:
        spec = driver.spec
        try:
            if spec.transport == "stdio":
                from mcp import ClientSession, StdioServerParameters
                from mcp.client.stdio import stdio_client

                params = StdioServerParameters(
                    command=spec.command, args=spec.args, env=spec.build_env()
                )
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await self._serve(driver, session, ready)
            elif spec.transport == "sse":
                from mcp import ClientSession
                from mcp.client.sse import sse_client

                async with sse_client(spec.url) as (read, write):
                    async with ClientSession(read, write) as session:
                        await self._serve(driver, session, ready)
            else:
                raise ValueError(f"Unknown transport '{spec.transport}'")
        except Exception as exc:
            driver.state = "failed"
            driver.error = str(exc)[:200]
            logger.warning("Driver %s failed: %s", spec.name, driver.error)
            bus.publish(DRIVER_FAILED, {
                "type": "driver_failed",
                "driver": spec.name,
                "error": driver.error,
            })
        finally:
            self._deregister(spec.name)
            driver.session = None
            if driver.state != "failed":
                driver.state = "stopped"
            if not ready.done():
                ready.set_result(False)

    async def _serve(self, driver: _Driver, session: Any, ready: asyncio.Future) -> None:
        spec = driver.spec
        await session.initialize()
        listed = await session.list_tools()
        driver.tools = [
            ToolMeta(
                driver=spec.name,
                name=tool.name,
                qualified=f"{spec.name}.{tool.name}",
                description=tool.description or "",
                tags=list(spec.tags),
            )
            for tool in listed.tools
        ]
        for meta in driver.tools:
            self._tools[meta.qualified] = meta
        driver.session = session
        driver.state = "mounted"
        logger.info("Driver %s mounted: %d tool(s)", spec.name, len(driver.tools))
        bus.publish(DRIVER_MOUNTED, {
            "type": "driver_mounted",
            "driver": spec.name,
            "tools": [m.qualified for m in driver.tools],
        })
        if not ready.done():
            ready.set_result(True)
        await driver.shutdown.wait()

    async def unmount_all(self) -> None:
        for driver in self._drivers.values():
            driver.shutdown.set()
        for driver in self._drivers.values():
            if driver.task:
                try:
                    await asyncio.wait_for(driver.task, timeout=10)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    driver.task.cancel()
        self._drivers.clear()
        self._tools.clear()

    def _deregister(self, driver_name: str) -> None:
        self._tools = {
            q: m for q, m in self._tools.items() if m.driver != driver_name
        }

    # ------------------------------------------------------------ inspection

    def snapshot(self) -> dict[str, Any]:
        return {
            name: {
                "state": d.state,
                "transport": d.spec.transport,
                "tags": d.spec.tags,
                "tools": len(d.tools),
                **({"error": d.error} if d.error else {}),
            }
            for name, d in self._drivers.items()
        }

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "qualified": m.qualified,
                "driver": m.driver,
                "description": m.description,
                "tags": m.tags,
            }
            for m in self._tools.values()
        ]

    # ------------------------------------------------------------ execution

    async def call_tool(
        self,
        qualified: str,
        arguments: dict[str, Any],
        *,
        skill_config: dict[str, Any],
        session_id: str = "",
        thread_id: str = "",
    ) -> Any:
        """Governed tool call: allowlist + Tier 0 exec gate + audit events."""
        meta = self._tools.get(qualified)
        if meta is None:
            raise ToolPermissionError(f"No such tool mounted: '{qualified}'")

        skill_name = skill_config.get("name", "?")
        try:
            check_tool_allowed(skill_config, qualified, tags=meta.tags)
        except ToolExecApprovalRequired:
            if self._interrupt_table is not None:
                self._interrupt_table.raise_tool_exec(
                    skill_name=skill_name,
                    session_id=session_id,
                    tool=qualified,
                    arguments_summary=str(arguments)[:200],
                    arguments=arguments,
                )
            bus.publish(TOOL_DENIED, {
                "type": "tool_denied",
                "tool": qualified,
                "skill": skill_name,
                "reason": "tool_exec_approval",
            }, session_id=session_id, thread_id=thread_id)
            raise
        except Exception:
            bus.publish(TOOL_DENIED, {
                "type": "tool_denied",
                "tool": qualified,
                "skill": skill_name,
                "reason": "not_allowed",
            }, session_id=session_id, thread_id=thread_id)
            raise

        driver = self._drivers.get(meta.driver)
        if driver is None or driver.state != "mounted" or driver.session is None:
            raise RuntimeError(f"Driver '{meta.driver}' is not mounted")

        result = await driver.session.call_tool(meta.name, arguments)
        payload: dict[str, Any] = {
            "type": "tool_called",
            "tool": qualified,
            "skill": skill_name,
        }
        if qualified == "gmail.send_draft":
            canonical = json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str)
            payload["arguments_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            payload["draft_id"] = arguments.get("draft_id")
        bus.publish(TOOL_CALLED, payload, session_id=session_id, thread_id=thread_id)
        return result


_host: MCPHost | None = None


def get_mcp_host() -> MCPHost:
    global _host
    if _host is None:
        from core.execution.context import interrupt_table

        _host = MCPHost(interrupt_table=interrupt_table)
    return _host
