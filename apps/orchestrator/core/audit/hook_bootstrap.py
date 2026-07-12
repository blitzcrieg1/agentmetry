"""Install global Tier B hooks on orchestrator boot (Cursor, etc.)."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CURSOR_HOOK_EVENTS = (
    "sessionStart",
    "sessionEnd",
    "stop",
    "beforeShellExecution",
    "afterShellExecution",
    "beforeMCPExecution",
    "afterMCPExecution",
    "preToolUse",
    "postToolUse",
    "postToolUseFailure",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _ingest_script(repo_root: Path | None = None) -> Path:
    root = repo_root or _repo_root()
    return root / "scripts" / "agentaudit_ingest.py"


def cursor_hooks_payload(*, python: str, ingest: Path) -> dict[str, Any]:
    hook_cmd = f'"{python}" "{ingest}" cursor hook'
    return {
        "version": 1,
        "hooks": {
            event: [{"command": f"{hook_cmd} {event}"}]
            for event in CURSOR_HOOK_EVENTS
        },
    }


def install_cursor_global_hooks(
    *,
    repo_root: Path | None = None,
    python: str | None = None,
    remove_project_hooks: bool = True,
) -> Path | None:
    """Write ~/.cursor/hooks.json so every Cursor workspace is audited."""
    root = repo_root or _repo_root()
    ingest = _ingest_script(root)
    if not ingest.is_file():
        logger.warning("Cursor hook bootstrap skipped: missing %s", ingest)
        return None

    py = python or sys.executable
    hooks_dir = Path.home() / ".cursor"
    hooks_path = hooks_dir / "hooks.json"
    payload = cursor_hooks_payload(python=py, ingest=ingest)

    hooks_dir.mkdir(parents=True, exist_ok=True)
    hooks_path.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info("Installed global Cursor audit hooks -> %s", hooks_path)

    if remove_project_hooks:
        project_hooks = root / ".cursor" / "hooks.json"
        if project_hooks.is_file():
            project_hooks.unlink()
            logger.info("Removed project Cursor hooks (global covers all workspaces): %s", project_hooks)

    return hooks_path


def bootstrap_tier_b_hooks(*, repo_root: Path | None = None) -> dict[str, str | None]:
    """Best-effort hook install for launch-and-forget Tier B logging."""
    results: dict[str, str | None] = {"cursor": None}
    try:
        path = install_cursor_global_hooks(repo_root=repo_root)
        results["cursor"] = str(path) if path else None
    except OSError as exc:
        logger.warning("Cursor hook bootstrap failed: %s", exc)
    return results


if __name__ == "__main__":
    paths = bootstrap_tier_b_hooks()
    if paths.get("cursor"):
        print(f"Installed global Cursor hooks -> {paths['cursor']}")
        sys.exit(0)
    print("Cursor hook install skipped (ingest script missing)", file=sys.stderr)
    sys.exit(1)
