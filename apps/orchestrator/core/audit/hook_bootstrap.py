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


# --- Claude Code (global ~/.claude/settings.json) -------------------------------
# Claude's settings.json is USER-OWNED (theme, permissions, MCP servers, env).
# We MERGE only the hooks we own — never overwrite the file. Uses the nested
# Claude Code hook schema: event -> [ { "hooks": [ { type, command } ] } ].

CLAUDE_HOOK_EVENTS = (
    "SessionStart",
    "PreToolUse",
    "PostToolUse",
    "Notification",
    "Stop",
)


def _claude_command(event: str, *, python: str, ingest: Path) -> str:
    return f'"{python}" "{ingest}" claude hook {event}'


def _is_our_claude_group(group: Any) -> bool:
    """True if a hook group is one AgentAudit installed (idempotency marker)."""
    if not isinstance(group, dict):
        return False
    for inner in group.get("hooks", []) or []:
        if isinstance(inner, dict) and "agentaudit_ingest.py" in str(inner.get("command", "")):
            return True
    return False


def merge_claude_hooks(
    settings: dict[str, Any], *, python: str, ingest: Path
) -> dict[str, Any]:
    """Deep-merge AgentAudit hooks into a Claude settings dict, non-destructively.

    Preserves every other key (theme, permissions, mcpServers, env) and any
    user hooks; replaces only our own previously-installed entries (idempotent).
    """
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        settings["hooks"] = hooks

    for event in CLAUDE_HOOK_EVENTS:
        existing = hooks.get(event)
        groups = existing if isinstance(existing, list) else []
        # Drop our prior entries so a re-run doesn't duplicate them.
        kept = [g for g in groups if not _is_our_claude_group(g)]
        kept.append({
            "hooks": [{
                "type": "command",
                "command": _claude_command(event, python=python, ingest=ingest),
                "timeout": 10,
            }],
        })
        hooks[event] = kept

    return settings


def install_claude_global_hooks(
    *, repo_root: Path | None = None, python: str | None = None
) -> Path | None:
    """Merge AgentAudit hooks into ~/.claude/settings.json for every Claude project."""
    root = repo_root or _repo_root()
    ingest = _ingest_script(root)
    if not ingest.is_file():
        logger.warning("Claude hook bootstrap skipped: missing %s", ingest)
        return None

    py = python or sys.executable
    settings_dir = Path.home() / ".claude"
    settings_path = settings_dir / "settings.json"

    settings: dict[str, Any] = {}
    if settings_path.is_file():
        try:
            loaded = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            # Never clobber a config we can't parse.
            logger.warning("Claude settings.json unreadable (%s); skipping install", exc)
            return None
        if not isinstance(loaded, dict):
            logger.warning("Claude settings.json is not an object; skipping install")
            return None
        settings = loaded

    merge_claude_hooks(settings, python=py, ingest=ingest)

    settings_dir.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    logger.info("Installed global Claude audit hooks -> %s", settings_path)
    return settings_path


def bootstrap_tier_b_hooks(*, repo_root: Path | None = None) -> dict[str, str | None]:
    """Best-effort hook install for launch-and-forget Tier B logging."""
    results: dict[str, str | None] = {"cursor": None, "claude": None}
    try:
        path = install_cursor_global_hooks(repo_root=repo_root)
        results["cursor"] = str(path) if path else None
    except OSError as exc:
        logger.warning("Cursor hook bootstrap failed: %s", exc)
    try:
        cpath = install_claude_global_hooks(repo_root=repo_root)
        results["claude"] = str(cpath) if cpath else None
    except OSError as exc:
        logger.warning("Claude hook bootstrap failed: %s", exc)
    return results


if __name__ == "__main__":
    paths = bootstrap_tier_b_hooks()
    installed = {k: v for k, v in paths.items() if v}
    if installed:
        for app, path in installed.items():
            print(f"Installed global {app} hooks -> {path}")
        sys.exit(0)
    print("Hook install skipped (ingest script missing)", file=sys.stderr)
    sys.exit(1)
