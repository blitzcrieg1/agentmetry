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


def read_runs_between(start_ts: str, end_ts: str) -> list[dict[str, Any]]:
    """Return run ledger rows whose ts falls in [start_ts, end_ts] (inclusive)."""
    path = audit_path()
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = row.get("ts", "")
        if start_ts <= ts <= end_ts:
            rows.append(row)
    return rows


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
