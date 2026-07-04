"""Driver specs — operator-owned config, resilient loading, scrubbed env."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

# Minimum a Windows subprocess needs to start node/python at all. Secrets like
# GEMINI_API_KEY never cross into a driver unless env_allow names them.
_BASE_ENV_NAMES = (
    "SYSTEMROOT",
    "PATH",
    "PATHEXT",
    "COMSPEC",
    "TEMP",
    "TMP",
    "APPDATA",
    "LOCALAPPDATA",
    "USERPROFILE",
    "PROGRAMFILES",
    "HOME",
)


def _orchestrator_env_file() -> Path:
    return Path(__file__).resolve().parents[2] / ".env"


def _dotenv_values() -> dict[str, str]:
    """Minimal KEY=VALUE parse of the orchestrator .env (gitignored secrets).

    pydantic-settings reads .env into Settings fields only — it never exports
    to os.environ — so env_allow names documented as ".env keys" (SERPER,
    GMAIL client creds, ...) would otherwise silently never reach a driver.
    """
    path = _orchestrator_env_file()
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    except OSError as exc:
        logger.warning("Could not read %s for driver env: %s", path, exc)
    return values


def base_subprocess_env(extra_names: list[str] | None = None) -> dict[str, str]:
    """Allowlist-only environment for any sandboxed/driver subprocess.

    Allowlisted names resolve from the live process env first, then fall back
    to the orchestrator's .env file. Base names never fall back — they are
    OS plumbing, not secrets.
    """
    result: dict[str, str] = {}
    for name in _BASE_ENV_NAMES:
        value = os.environ.get(name)
        if value is not None:
            result[name] = value
    if extra_names:
        dotenv = _dotenv_values()
        for name in extra_names:
            value = os.environ.get(name, dotenv.get(name))
            if value is not None:
                result[name] = value
    return result


class DriverSpec(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9_-]+$")
    transport: str = "stdio"  # stdio | sse
    command: str = ""
    args: list[str] = Field(default_factory=list)
    url: str = ""
    env: dict[str, str] = Field(default_factory=dict)
    env_allow: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True

    def build_env(self) -> dict[str, str]:
        """Allowlist-only environment for the driver subprocess."""
        result = base_subprocess_env(self.env_allow)
        result.update(self.env)
        return result


def load_driver_specs(config_path: Path) -> list[DriverSpec]:
    """Read drivers.json; a malformed entry never blocks the others."""
    if not config_path.exists():
        return []
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("drivers.json unreadable (%s) — no drivers mounted", exc)
        return []

    specs: list[DriverSpec] = []
    for entry in data.get("drivers", []):
        try:
            spec = DriverSpec.model_validate(entry)
        except ValidationError as exc:
            logger.warning("Skipping invalid driver entry %r: %s", entry.get("name"), exc)
            continue
        if not spec.enabled:
            logger.info("Driver %s is disabled — skipped", spec.name)
            continue
        specs.append(spec)
    return specs
