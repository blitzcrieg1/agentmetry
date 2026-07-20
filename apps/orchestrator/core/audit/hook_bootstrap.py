"""Install global Tier B hooks on orchestrator boot (Cursor, etc.)."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Hook subprocesses read these from orchestrator .env (Claude also gets them in settings env).
HOOK_ENV_KEYS = (
    "AGENTMETRY_TOOL_POLICY_MODE",
    "AGENTMETRY_DLP_MODE",
    "AGENTMETRY_URL",
)

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
    return root / "scripts" / "agentmetry_ingest.py"


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

# Qwen Code and Kimi Code — Claude-compatible wire protocol (JSON stdin).
FAMILY_HOOK_EVENTS = (
    "SessionStart",
    "SessionEnd",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "SubagentStart",
    "SubagentStop",
    "Stop",
)

KIMI_HOOKS_BEGIN = "# agentmetry hooks begin"
KIMI_HOOKS_END = "# agentmetry hooks end"


def _orchestrator_env_path(repo_root: Path | None = None) -> Path:
    root = repo_root or _repo_root()
    return root / "apps" / "orchestrator" / ".env"


def merge_claude_hook_env(
    settings: dict[str, Any], *, repo_root: Path | None = None
) -> dict[str, Any]:
    """Mirror hook-relevant keys from orchestrator .env into Claude settings env."""
    from core.diagnostics.env_file import read_env_key

    env_path = _orchestrator_env_path(repo_root)
    env = settings.get("env")
    if not isinstance(env, dict):
        env = {}
    for key in HOOK_ENV_KEYS:
        val = read_env_key(env_path, key)
        if val:
            env[key] = val
    if env:
        settings["env"] = env
    return settings


def _claude_command(event: str, *, python: str, ingest: Path) -> str:
    return f'"{python}" "{ingest}" claude hook {event}'


def _family_command(source_app: str, event: str, *, python: str, ingest: Path) -> str:
    return f'"{python}" "{ingest}" {source_app} hook {event}'


def _is_our_hook_group(group: Any, *, source_app: str | None = None) -> bool:
    """True if a hook group is one Agentmetry installed (idempotency marker)."""
    if not isinstance(group, dict):
        return False
    needle = f'"{source_app} hook' if source_app else "agentmetry_ingest.py"
    for inner in group.get("hooks", []) or []:
        cmd = str(inner.get("command", ""))
        if "agentmetry_ingest.py" in cmd or "agentaudit_ingest.py" in cmd:
            if source_app is None or f"{source_app} hook" in cmd:
                return True
    return False


def _is_our_claude_group(group: Any) -> bool:
    return _is_our_hook_group(group, source_app="claude")


def merge_family_hooks(
    settings: dict[str, Any],
    *,
    events: tuple[str, ...],
    source_app: str,
    python: str,
    ingest: Path,
) -> dict[str, Any]:
    """Deep-merge Agentmetry hooks into a Claude-family settings dict."""
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        settings["hooks"] = hooks

    for event in events:
        existing = hooks.get(event)
        groups = existing if isinstance(existing, list) else []
        kept = [g for g in groups if not _is_our_hook_group(g, source_app=source_app)]
        kept.append({
            "hooks": [{
                "type": "command",
                "command": _family_command(source_app, event, python=python, ingest=ingest),
                "timeout": 10,
            }],
        })
        hooks[event] = kept

    return settings


def merge_claude_hooks(
    settings: dict[str, Any], *, python: str, ingest: Path
) -> dict[str, Any]:
    """Deep-merge Agentmetry hooks into a Claude settings dict, non-destructively.

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
    """Merge Agentmetry hooks into ~/.claude/settings.json for every Claude project."""
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
    merge_claude_hook_env(settings, repo_root=root)

    settings_dir.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    logger.info("Installed global Claude audit hooks -> %s", settings_path)
    return settings_path


def _qwen_settings_dir() -> Path:
    home = os.environ.get("QWEN_HOME", "").strip()
    if home:
        return Path(home).expanduser()
    return Path.home() / ".qwen"


def install_qwen_global_hooks(
    *, repo_root: Path | None = None, python: str | None = None
) -> Path | None:
    """Merge Agentmetry hooks into ~/.qwen/settings.json for every Qwen Code project."""
    return _install_family_settings_hooks(
        "qwen", _qwen_settings_dir(), repo_root=repo_root, python=python
    )


def _qoder_settings_dir() -> Path:
    return Path.home() / ".qoder"


def install_qoder_global_hooks(
    *, repo_root: Path | None = None, python: str | None = None
) -> Path | None:
    """Merge Agentmetry hooks into ~/.qoder/settings.json (Qoder / 通义灵码)."""
    return _install_family_settings_hooks(
        "qoder", _qoder_settings_dir(), repo_root=repo_root, python=python
    )


def _codebuddy_settings_dir() -> Path:
    return Path.home() / ".codebuddy"


def install_codebuddy_global_hooks(
    *, repo_root: Path | None = None, python: str | None = None
) -> Path | None:
    """Merge Agentmetry hooks into ~/.codebuddy/settings.json (Tencent CodeBuddy)."""
    return _install_family_settings_hooks(
        "codebuddy", _codebuddy_settings_dir(), repo_root=repo_root, python=python
    )


def _install_family_settings_hooks(
    source_app: str,
    settings_dir: Path,
    *,
    repo_root: Path | None = None,
    python: str | None = None,
) -> Path | None:
    root = repo_root or _repo_root()
    ingest = _ingest_script(root)
    if not ingest.is_file():
        logger.warning("%s hook bootstrap skipped: missing %s", source_app, ingest)
        return None

    py = python or sys.executable
    settings_path = settings_dir / "settings.json"

    settings: dict[str, Any] = {}
    if settings_path.is_file():
        try:
            loaded = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("%s settings.json unreadable (%s); skipping install", source_app, exc)
            return None
        if not isinstance(loaded, dict):
            logger.warning("%s settings.json is not an object; skipping install", source_app)
            return None
        settings = loaded

    merge_family_hooks(
        settings,
        events=FAMILY_HOOK_EVENTS,
        source_app=source_app,
        python=py,
        ingest=ingest,
    )

    settings_dir.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    logger.info("Installed global %s audit hooks -> %s", source_app, settings_path)
    return settings_path


def _kimi_config_dir() -> Path:
    home = os.environ.get("KIMI_CODE_HOME", "").strip()
    if home:
        return Path(home).expanduser()
    return Path.home() / ".kimi-code"


def kimi_hooks_toml_block(*, python: str, ingest: Path) -> str:
    lines = [
        KIMI_HOOKS_BEGIN,
        "# Managed by Agentmetry — re-run scripts/install_kimi_hooks.ps1 to update",
    ]
    for event in FAMILY_HOOK_EVENTS:
        cmd = _family_command("kimi", event, python=python, ingest=ingest)
        lines.extend([
            "[[hooks]]",
            f'event = "{event}"',
            'matcher = ".*"',
            f'command = "{cmd}"',
            "timeout = 10",
            "",
        ])
    lines.append(KIMI_HOOKS_END)
    return "\n".join(lines) + "\n"


def merge_kimi_hooks_toml(text: str, block: str) -> str:
    pattern = re.compile(
        rf"{re.escape(KIMI_HOOKS_BEGIN)}.*?{re.escape(KIMI_HOOKS_END)}\n?",
        re.DOTALL,
    )
    stripped = pattern.sub("", text)
    if stripped and not stripped.endswith("\n"):
        stripped += "\n"
    if stripped.strip():
        return stripped + "\n" + block
    return block


def install_kimi_global_hooks(
    *, repo_root: Path | None = None, python: str | None = None
) -> Path | None:
    """Append Agentmetry hooks to ~/.kimi-code/config.toml (TOML [[hooks]] tables)."""
    root = repo_root or _repo_root()
    ingest = _ingest_script(root)
    if not ingest.is_file():
        logger.warning("Kimi hook bootstrap skipped: missing %s", ingest)
        return None

    py = python or sys.executable
    config_dir = _kimi_config_dir()
    config_path = config_dir / "config.toml"
    block = kimi_hooks_toml_block(python=py, ingest=ingest)

    existing = ""
    if config_path.is_file():
        existing = config_path.read_text(encoding="utf-8")

    config_dir.mkdir(parents=True, exist_ok=True)
    config_path.write_text(merge_kimi_hooks_toml(existing, block), encoding="utf-8")
    logger.info("Installed global Kimi audit hooks -> %s", config_path)
    return config_path


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
    target = sys.argv[1] if len(sys.argv) > 1 else "bootstrap"
    installers = {
        "bootstrap": bootstrap_tier_b_hooks,
        "qwen": install_qwen_global_hooks,
        "kimi": install_kimi_global_hooks,
        "qoder": install_qoder_global_hooks,
        "codebuddy": install_codebuddy_global_hooks,
    }
    fn = installers.get(target, bootstrap_tier_b_hooks)
    if target in ("qwen", "kimi", "qoder", "codebuddy"):
        path = fn()
        if path:
            print(f"Installed global {target} hooks -> {path}")
            sys.exit(0)
        print(f"{target} hook install skipped (ingest script missing)", file=sys.stderr)
        sys.exit(1)
    paths = bootstrap_tier_b_hooks()
    installed = {k: v for k, v in paths.items() if v}
    if installed:
        for app, path in installed.items():
            print(f"Installed global {app} hooks -> {path}")
        sys.exit(0)
    print("Hook install skipped (ingest script missing)", file=sys.stderr)
    sys.exit(1)
