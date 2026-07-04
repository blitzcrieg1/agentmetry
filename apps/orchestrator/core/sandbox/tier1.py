"""Sandbox Tier 1 — restricted subprocess execution.

Containment of accidents, not adversaries: allowlisted binaries only, working
directory jailed to the vault, scrubbed environment, hard timeout, no shell.
Real filesystem/network isolation is Tier 2+ (WSL2/containers) territory.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path

from core.config import settings
from core.drivers.spec import base_subprocess_env

_MAX_OUTPUT_BYTES = 64 * 1024


class SandboxDenied(Exception):
    """The execution request violates Tier 1 policy."""


@dataclass
class ExecutionResult:
    argv: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False


def _allowed_commands() -> tuple[str, ...]:
    return tuple(
        name.strip().lower()
        for name in settings.sandbox_tier1_allowed.split(",")
        if name.strip()
    )


def _command_name(argv0: str) -> str:
    name = Path(argv0).name.lower()
    return name[:-4] if name.endswith(".exe") else name


def _jailed_cwd(cwd: Path | None) -> Path:
    vault_root = Path(settings.vault_path).resolve()
    target = (cwd or vault_root).resolve()
    if target != vault_root and vault_root not in target.parents:
        raise SandboxDenied(f"cwd escapes the vault jail: {target}")
    if not target.is_dir():
        raise SandboxDenied(f"cwd does not exist: {target}")
    return target


def _truncate(data: bytes) -> str:
    text = data[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
    if len(data) > _MAX_OUTPUT_BYTES:
        text += "\n...[truncated]"
    return text


async def run_tier1(
    argv: list[str],
    *,
    cwd: Path | None = None,
    timeout_s: float = 30.0,
    allowlist: tuple[str, ...] | None = None,
) -> ExecutionResult:
    """Run an allowlisted command inside the vault jail."""
    if not argv or not all(isinstance(a, str) for a in argv):
        raise SandboxDenied("argv must be a non-empty list of strings")

    allowed = allowlist if allowlist is not None else _allowed_commands()
    command = _command_name(argv[0])
    if command not in allowed:
        raise SandboxDenied(
            f"Command '{command}' is not in the Tier 1 allowlist {list(allowed)}"
        )

    workdir = _jailed_cwd(cwd)
    start = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(workdir),
        env=base_subprocess_env(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.DEVNULL,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        timed_out = False
    except asyncio.TimeoutError:
        proc.kill()
        stdout, stderr = await proc.communicate()
        timed_out = True

    return ExecutionResult(
        argv=list(argv),
        exit_code=proc.returncode if proc.returncode is not None else -1,
        stdout=_truncate(stdout),
        stderr=_truncate(stderr),
        duration_ms=int((time.monotonic() - start) * 1000),
        timed_out=timed_out,
    )
