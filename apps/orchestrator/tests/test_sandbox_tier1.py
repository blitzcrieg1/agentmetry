"""Sandbox Tier 1: allowlist, jail, timeout, env scrubbing."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from core.config import settings
from core.sandbox.tier1 import SandboxDenied, run_tier1


@pytest.fixture(autouse=True)
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    v = tmp_path / "vault"
    v.mkdir()
    monkeypatch.setattr(settings, "vault_path", v)
    return v


async def test_unknown_binary_denied():
    with pytest.raises(SandboxDenied, match="not in the Tier 1 allowlist"):
        await run_tier1(["definitely-not-allowed", "--help"], allowlist=("git",))


async def test_empty_argv_denied():
    with pytest.raises(SandboxDenied):
        await run_tier1([], allowlist=("git",))


async def test_cwd_escape_denied(vault: Path):
    with pytest.raises(SandboxDenied, match="escapes the vault jail"):
        await run_tier1(["git", "status"], cwd=vault.parent, allowlist=("git",))


async def test_allowed_command_runs_python(vault: Path):
    # python is universally present in CI; prove the happy path end to end.
    result = await run_tier1(
        [sys.executable, "-c", "print('sandboxed-ok')"],
        allowlist=(Path(sys.executable).name.lower().removesuffix(".exe"),),
    )
    assert result.exit_code == 0
    assert "sandboxed-ok" in result.stdout
    assert result.timed_out is False


async def test_timeout_kills_long_process(vault: Path):
    result = await run_tier1(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        timeout_s=0.5,
        allowlist=(Path(sys.executable).name.lower().removesuffix(".exe"),),
    )
    assert result.timed_out is True
    assert result.exit_code != 0


async def test_env_is_scrubbed(vault: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GEMINI_API_KEY", "super-secret")
    result = await run_tier1(
        [sys.executable, "-c", "import os; print(os.environ.get('GEMINI_API_KEY', 'ABSENT'))"],
        allowlist=(Path(sys.executable).name.lower().removesuffix(".exe"),),
    )
    assert "ABSENT" in result.stdout
    assert "super-secret" not in result.stdout


@pytest.mark.skipif(
    subprocess.run(["git", "--version"], capture_output=True).returncode != 0,
    reason="git not available",
)
async def test_vault_scoped_git_status(vault: Path):
    subprocess.run(["git", "init"], cwd=vault, capture_output=True)
    (vault / "note.md").write_text("hello", encoding="utf-8")
    result = await run_tier1(["git", "status", "--porcelain"], cwd=vault, allowlist=("git",))
    assert result.exit_code == 0
    assert "note.md" in result.stdout
