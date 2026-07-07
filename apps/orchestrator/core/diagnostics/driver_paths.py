"""Portable driver path tokens and drivers.json normalization."""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from core.config import settings
from core.drivers.spec import DriverSpec

logger = logging.getLogger(__name__)

_ORCH_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = _ORCH_ROOT.parents[1]

TOKEN_PYTHON = "{PYTHON}"
TOKEN_ORCH = "{ORCHESTRATOR_ROOT}"
TOKEN_REPO = "{REPO_ROOT}"
TOKEN_VAULT = "{VAULT_PATH}"

_PORTABLE_TOKENS = (TOKEN_PYTHON, TOKEN_ORCH, TOKEN_REPO, TOKEN_VAULT)

_ABSOLUTE_PATH_RE = re.compile(
    r"(?:[A-Za-z]:[\\/]|/Users/|/home/|C:/Users/|C:\\Users\\)"
)


def orchestrator_root() -> Path:
    return _ORCH_ROOT


def repo_root() -> Path:
    return _REPO_ROOT


def default_python() -> str:
    venv_py = _ORCH_ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_py.is_file():
        return str(venv_py)
    venv_bin = _ORCH_ROOT / ".venv" / "bin" / "python"
    if venv_bin.is_file():
        return str(venv_bin)
    return sys.executable


def placeholder_map(vault_path: Path | None = None) -> dict[str, str]:
    vault = Path(vault_path or settings.vault_path).resolve()
    return {
        TOKEN_PYTHON: default_python().replace("\\", "/"),
        TOKEN_ORCH: str(_ORCH_ROOT.resolve()).replace("\\", "/"),
        TOKEN_REPO: str(_REPO_ROOT.resolve()).replace("\\", "/"),
        TOKEN_VAULT: str(vault).replace("\\", "/"),
    }


def expand_placeholders(value: str, *, vault_path: Path | None = None) -> str:
    text = value.replace("\\", "/")
    for token, resolved in placeholder_map(vault_path).items():
        text = text.replace(token, resolved)
    return text


def collapse_to_portable(value: str, *, vault_path: Path | None = None) -> str:
    text = value.replace("\\", "/")
    mapping = placeholder_map(vault_path)
    py = mapping[TOKEN_PYTHON]
    if py and py in text:
        return text.replace(py, TOKEN_PYTHON)
    for token, resolved in sorted(mapping.items(), key=lambda kv: len(kv[1]), reverse=True):
        if token == TOKEN_PYTHON:
            continue
        if resolved and resolved in text:
            text = text.replace(resolved, token)
    return text


def resolve_driver_entry(entry: dict[str, Any], *, vault_path: Path | None = None) -> dict[str, Any]:
    resolved = dict(entry)
    command = resolved.get("command")
    if isinstance(command, str):
        resolved["command"] = expand_placeholders(command, vault_path=vault_path)
    args = resolved.get("args") or []
    resolved["args"] = [
        expand_placeholders(arg, vault_path=vault_path) if isinstance(arg, str) else arg
        for arg in args
    ]
    return resolved


def normalize_driver_entry(entry: dict[str, Any], *, vault_path: Path | None = None) -> dict[str, Any]:
    normalized = dict(entry)
    command = normalized.get("command")
    if isinstance(command, str):
        normalized["command"] = collapse_to_portable(command, vault_path=vault_path)
    args = normalized.get("args") or []
    normalized["args"] = [
        collapse_to_portable(arg, vault_path=vault_path) if isinstance(arg, str) else arg
        for arg in args
    ]
    return normalized


def entry_has_absolute_paths(entry: dict[str, Any]) -> bool:
    parts: list[str] = []
    if isinstance(entry.get("command"), str):
        parts.append(entry["command"])
    for arg in entry.get("args") or []:
        if isinstance(arg, str):
            parts.append(arg)
    combined = " ".join(parts)
    if any(token in combined for token in _PORTABLE_TOKENS):
        return False
    return bool(_ABSOLUTE_PATH_RE.search(combined))


def load_resolved_driver_specs(config_path: Path, *, vault_path: Path | None = None) -> list[DriverSpec]:
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
            resolved = resolve_driver_entry(entry, vault_path=vault_path)
            spec = DriverSpec.model_validate(resolved)
        except ValidationError as exc:
            logger.warning("Skipping invalid driver entry %r: %s", entry.get("name"), exc)
            continue
        if not spec.enabled:
            logger.info("Driver %s is disabled — skipped", spec.name)
            continue
        if spec.name == "gmail":
            env = dict(spec.env)
            env["BLACKBOX_GMAIL_SEND_ENABLED"] = "1" if settings.gmail_send_enabled else "0"
            spec = spec.model_copy(update={"env": env})
        specs.append(spec)
    return specs


def normalize_drivers_file(config_path: Path, *, vault_path: Path | None = None) -> bool:
    if not config_path.exists():
        return False
    data = json.loads(config_path.read_text(encoding="utf-8"))
    drivers = data.get("drivers") or []
    normalized = [normalize_driver_entry(entry, vault_path=vault_path) for entry in drivers]
    if normalized == drivers:
        return False
    data["drivers"] = normalized
    config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True
