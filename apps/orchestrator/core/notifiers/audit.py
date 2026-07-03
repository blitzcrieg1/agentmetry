"""Structured run audit log (JSONL)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import settings
from core.memory.obsidian_client import ObsidianClient


def audit_path() -> Path:
    root = Path(__file__).resolve().parents[2] / "data"
    root.mkdir(parents=True, exist_ok=True)
    return root / "runs.jsonl"


def log_run(event: dict[str, Any]) -> None:
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        **event,
    }
    path = audit_path()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, default=str) + "\n")


def append_vault_run_log(line: str) -> None:
    """Append to vault/.system/run-log.md for Obsidian-visible history."""
    obsidian = ObsidianClient(settings.vault_path)
    log_path = settings.vault_path / ".system" / "run-log.md"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    entry = f"- **{ts}** — {line}\n"
    if log_path.exists():
        content = log_path.read_text(encoding="utf-8")
    else:
        content = "# BLACKBOX Run Log\n\nAutonomous and manual skill executions.\n\n"
    obsidian.write_system_note("run-log.md", content + entry)
