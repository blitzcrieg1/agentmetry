"""Install global Tier B hooks on orchestrator boot (Cursor, etc.)."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

from agentmetry.core.paths import user_profile_dir

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
    return Path(__file__).resolve().parents[5]


def _ingest_script(repo_root: Path | None = None) -> Path:
    root = repo_root or _repo_root()
    return root / "scripts" / "agentmetry_ingest.py"


def cursor_hooks_payload(
    *, python: str, ingest: Path, repo_root: Path | None = None
) -> dict[str, Any]:
    return {
        "version": 1,
        "hooks": {
            event: [
                {
                    "command": hook_command(
                        "cursor", event, python=python, ingest=ingest, repo_root=repo_root
                    )
                }
            ]
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
    if hook_target(root) == "none":
        # No checkout, no frozen binary, no console script: nothing a hook
        # could invoke. Writing a config here would look like coverage.
        logger.warning(
            "Cursor hook bootstrap skipped: no way to reach ingest from %s", root
        )
        return None

    py = python or sys.executable
    hooks_dir = user_profile_dir() / ".cursor"
    hooks_path = hooks_dir / "hooks.json"
    payload = cursor_hooks_payload(python=py, ingest=ingest, repo_root=root)

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

#: Every executable an Agentmetry hook command can name. `hook_coverage` reads
#: this same tuple, so a new invocation form cannot be recognised by one and not
#: the other.
HOOK_COMMAND_TOKENS = (
    "agentmetry_ingest",      # repo checkout, and every hook installed to date
    "agentaudit_ingest",      # pre-0.4.0 rename, still on disk somewhere
    "agentmetry-hook",        # wheel install console script
    "agentmetry.exe",         # frozen binary from the MSI
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
    from agentmetry.core.diagnostics.env_file import read_env_key

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


def _console_script() -> Path | None:
    """The `agentmetry-hook` console script, if this interpreter has one.

    Installed beside the interpreter: Scripts/ on Windows, bin/ elsewhere.
    """
    bindir = Path(sys.executable).resolve().parent
    for name in ("agentmetry-hook.exe", "agentmetry-hook"):
        candidate = bindir / name
        if candidate.is_file():
            return candidate
    return None


def ephemeral_environment(executable: str | None = None) -> str:
    """Why this interpreter is a temporary one, or "" when it will still exist later.

    `uvx agentmetry ...` and `pipx run agentmetry ...` run from a cache the tool
    may delete at any time (`uv cache clean`, a pipx cache expiry). A hook
    config written from there names an executable inside that cache: it works
    today, and after the next clean every hook fails. Most agents treat a
    failing hook as a non-blocking error, so recording stops without a word;
    Copilot CLI fails closed on a broken pre-tool hook and blocks every tool
    call. Coverage would still report the agent covered, because it checks the
    hook text in the config, not the file it points at.
    """
    raw = executable or sys.executable
    try:
        resolved = Path(raw).resolve()
    except OSError:
        resolved = Path(raw)
    # Split on both separators by hand: on POSIX a Windows path is one part.
    text = str(resolved).replace("\\", "/").lower()
    parts = [p for p in text.split("/") if p]
    cache = os.environ.get("UV_CACHE_DIR", "").strip()
    if cache and text.startswith(str(Path(cache).resolve()).replace("\\", "/").lower() + "/"):
        return f"this interpreter is inside uv's cache ({resolved})"
    if "uv" in parts and ("archive-v0" in parts or "builds-v0" in parts):
        return f"this interpreter is inside uv's cache ({resolved})"
    if "pipx" in parts and ".cache" in parts:
        return f"this interpreter is inside pipx's run cache ({resolved})"
    return ""


def hook_target(repo_root: Path | None = None) -> str:
    """Which of the three ways to reach ingest exists here: repo, frozen, wheel.

    Order matters, and repo wins deliberately. On a developer machine with an
    editable install every option resolves, and switching those machines to a
    different invocation would rewrite working hook configs for no benefit. The
    other two exist for the case that used to have no answer at all: an MSI or
    wheel install, where `scripts/agentmetry_ingest.py` is simply not present
    and every installer bailed out.
    """
    if _ingest_script(repo_root).is_file():
        return "repo"
    if getattr(sys, "frozen", False):
        return "frozen"
    if _console_script() is not None:
        return "console"
    return "none"


def hook_command(
    source_app: str,
    event: str,
    *,
    python: str | None = None,
    ingest: Path | None = None,
    repo_root: Path | None = None,
) -> str:
    """The command an IDE hook config should invoke on this machine.

    Returns a whole command rather than a prefix callers append to. The three
    forms do not share an argument order, and pretending they did is how a
    frozen install would end up writing `agentmetry.exe hook cursor hook
    PreToolUse`.

    `repo_root` has to be threaded in by the caller. The installers gate on
    `hook_target(root)` and then built their command here, where `repo_root`
    was None and the target was re-derived from `_repo_root()` instead. Two
    decisions about which form to write, taken from two different roots. They
    agree whenever the caller passed no root, which is every production call
    today, and that is the only reason this has never produced a hook config
    pointing at a script that is not there.
    """
    target = hook_target(repo_root)
    if target == "frozen":
        return f'"{Path(sys.executable).resolve()}" hook {source_app} {event}'
    if target == "console":
        return f'"{_console_script()}" {source_app} hook {event}'
    py = python or sys.executable
    script = ingest if ingest is not None else _ingest_script(repo_root)
    return f'"{py}" "{script}" {source_app} hook {event}'


def _short_path(path: str) -> str:
    """The 8.3 short form of a Windows path, or the path unchanged."""
    if os.name != "nt":
        return path
    try:
        import ctypes

        size = ctypes.windll.kernel32.GetShortPathNameW(path, None, 0)
        if not size:
            return path
        buf = ctypes.create_unicode_buffer(size)
        if not ctypes.windll.kernel32.GetShortPathNameW(path, buf, size):
            return path
        return buf.value or path
    except (AttributeError, OSError):
        return path


def windows_hook_command(command: str) -> str:
    """`command` in a form that runs whichever way Codex launches it on Windows.

    `hook_command` quotes every path. Codex on Windows ran that form as
    "completed" and nothing arrived: under `cmd /c` the quoted first token
    breaks cmd's quote stripping, and under PowerShell a command that starts
    with a quoted string is a string, not a call. Both exit 1 and the hook
    never reaches ingest. The unquoted form runs under cmd, PowerShell and
    direct execution alike, which matters because Codex does not document
    which it uses. A path with a space is replaced by its 8.3 short name; one
    that has none keeps its quotes, and is still no worse than before.
    """
    out = []
    for token in re.findall(r'"[^"]*"|\S+', command):
        if token.startswith('"') and token.endswith('"'):
            inner = token[1:-1]
            if " " in inner:
                inner = _short_path(inner)
            token = inner if " " not in inner else f'"{inner}"'
        out.append(token)
    return " ".join(out)


def _claude_command(
    event: str, *, python: str, ingest: Path, repo_root: Path | None = None
) -> str:
    return hook_command("claude", event, python=python, ingest=ingest, repo_root=repo_root)


def _family_command(
    source_app: str, event: str, *, python: str, ingest: Path, repo_root: Path | None = None
) -> str:
    return hook_command(
        source_app, event, python=python, ingest=ingest, repo_root=repo_root
    )


def _is_our_hook_group(group: Any, *, source_app: str | None = None) -> bool:
    """True if a hook group is one Agentmetry installed (idempotency marker)."""
    if not isinstance(group, dict):
        return False
    for inner in group.get("hooks", []) or []:
        cmd = str(inner.get("command", ""))
        if not any(token in cmd for token in HOOK_COMMAND_TOKENS):
            continue
        # Matched on the app as a bare word rather than on "<app> hook",
        # because the frozen form is "<exe> hook <app> <event>" and the other
        # two are "<app> hook <event>". Keying on one order would silently
        # stop recognising our own groups on an MSI install.
        if source_app is None or source_app in cmd.split():
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
    repo_root: Path | None = None,
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
                "command": _family_command(
                    source_app, event, python=python, ingest=ingest, repo_root=repo_root
                ),
                "timeout": 10,
            }],
        })
        hooks[event] = kept

    return settings


def merge_claude_hooks(
    settings: dict[str, Any], *, python: str, ingest: Path, repo_root: Path | None = None
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
                "command": _claude_command(
                    event, python=python, ingest=ingest, repo_root=repo_root
                ),
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
    if hook_target(root) == "none":
        # No checkout, no frozen binary, no console script: nothing a hook
        # could invoke. Writing a config here would look like coverage.
        logger.warning(
            "Claude hook bootstrap skipped: no way to reach ingest from %s", root
        )
        return None

    py = python or sys.executable
    settings_dir = user_profile_dir() / ".claude"
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

    merge_claude_hooks(settings, python=py, ingest=ingest, repo_root=root)
    merge_claude_hook_env(settings, repo_root=root)

    settings_dir.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    logger.info("Installed global Claude audit hooks -> %s", settings_path)
    return settings_path


def _qwen_settings_dir() -> Path:
    home = os.environ.get("QWEN_HOME", "").strip()
    if home:
        return Path(home).expanduser()
    return user_profile_dir() / ".qwen"


def install_qwen_global_hooks(
    *, repo_root: Path | None = None, python: str | None = None
) -> Path | None:
    """Merge Agentmetry hooks into ~/.qwen/settings.json for every Qwen Code project."""
    return _install_family_settings_hooks(
        "qwen", _qwen_settings_dir(), repo_root=repo_root, python=python
    )


def _qoder_settings_dir() -> Path:
    return user_profile_dir() / ".qoder"


def install_qoder_global_hooks(
    *, repo_root: Path | None = None, python: str | None = None
) -> Path | None:
    """Merge Agentmetry hooks into ~/.qoder/settings.json (Qoder / 通义灵码)."""
    return _install_family_settings_hooks(
        "qoder", _qoder_settings_dir(), repo_root=repo_root, python=python
    )


def _codebuddy_settings_dir() -> Path:
    return user_profile_dir() / ".codebuddy"


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
    if hook_target(repo_root) == "none":
        logger.warning(
            "%s hook bootstrap skipped: no way to reach ingest", source_app
        )
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
        repo_root=root,
        ingest=ingest,
    )

    settings_dir.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    logger.info("Installed global %s audit hooks -> %s", source_app, settings_path)
    return settings_path


# --- OpenAI Codex CLI (global ~/.codex/hooks.json) ------------------------------
# Codex is the one supported agent that had no installer, so the only path was a
# hand-merge of adapters/codex/hooks.agentmetry.json. That template also carries
# a relative `python scripts/...` command, which only works when Codex happens to
# start in the repo root. This writes absolute paths, like every other installer.
#
# Codex groups carry a `matcher`, and unlike Claude the file holds nothing but
# hooks. It is still user-owned: a developer can add their own groups, so this
# merges and replaces only what we previously wrote.
CODEX_HOOK_EVENTS: tuple[tuple[str, str], ...] = (
    ("SessionStart", "startup|resume|clear"),
    ("PreToolUse", ".*"),
    ("PermissionRequest", ".*"),
    ("PostToolUse", ".*"),
    ("Stop", ""),
)


def merge_codex_hooks(
    doc: dict[str, Any],
    *,
    python: str,
    ingest: Path,
    repo_root: Path | None = None,
    windows: bool | None = None,
) -> dict[str, Any]:
    """Merge our groups into a Codex hooks document, non-destructively.

    Idempotent by the same marker every other adapter uses: a re-run drops the
    groups whose command names `codex hook` and appends fresh ones, so the file
    does not grow a duplicate set each time somebody runs the installer.
    """
    hooks = doc.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        doc["hooks"] = hooks

    for event, matcher in CODEX_HOOK_EVENTS:
        existing = hooks.get(event)
        groups = existing if isinstance(existing, list) else []
        kept = [g for g in groups if not _is_our_hook_group(g, source_app="codex")]
        command = _family_command("codex", event, python=python, ingest=ingest, repo_root=repo_root)
        handler: dict[str, Any] = {
            "type": "command",
            "command": command,
            "timeout": 10,
            "statusMessage": f"Agentmetry {event}",
        }
        if windows if windows is not None else os.name == "nt":
            # Codex's documented Windows override. See windows_hook_command.
            handler["commandWindows"] = windows_hook_command(command)
        group: dict[str, Any] = {"hooks": [handler]}
        if matcher:
            group["matcher"] = matcher
        kept.append(group)
        hooks[event] = kept

    return doc


def install_codex_global_hooks(
    *, repo_root: Path | None = None, python: str | None = None
) -> Path | None:
    """Merge Agentmetry hooks into ~/.codex/hooks.json for every Codex session.

    Deliberately not called from `bootstrap_tier_b_hooks`. Codex gates hooks
    behind a hash-based trust prompt and skips untrusted ones silently, so an
    install the developer did not ask for would sit there looking installed and
    capturing nothing. Installing it is a decision, and the decision comes with
    a step only a human can complete.
    """
    root = repo_root or _repo_root()
    ingest = _ingest_script(root)
    if hook_target(root) == "none":
        # No checkout, no frozen binary, no console script: nothing a hook
        # could invoke. Writing a config here would look like coverage.
        logger.warning(
            "Codex hook bootstrap skipped: no way to reach ingest from %s", root
        )
        return None

    py = python or sys.executable
    hooks_dir = user_profile_dir() / ".codex"
    hooks_path = hooks_dir / "hooks.json"

    doc: dict[str, Any] = {}
    if hooks_path.is_file():
        try:
            loaded = json.loads(hooks_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            # Never clobber a config we cannot parse.
            logger.warning("Codex hooks.json unreadable (%s); skipping install", exc)
            return None
        if not isinstance(loaded, dict):
            logger.warning("Codex hooks.json is not an object; skipping install")
            return None
        doc = loaded

    merge_codex_hooks(doc, python=py, ingest=ingest, repo_root=root)

    hooks_dir.mkdir(parents=True, exist_ok=True)
    hooks_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    logger.info("Installed global Codex audit hooks -> %s", hooks_path)
    grant_codex_sandbox_ingest()
    return hooks_path


def grant_codex_sandbox_ingest() -> list[str]:
    """Let Codex's Windows sandbox accounts read the ingest-only token.

    Codex's default Windows sandbox runs hooks as its own local accounts. They
    can run the hook and reach the recorder, but cannot read a token restricted
    to the developer, so every event was refused and lost without a word
    (#302). What they are granted is the ingest-only token: it posts events and
    nothing else, so a sandboxed agent gains no read of the trail and no say in
    triage. Returns the accounts granted; empty where there are none.
    """
    from agentmetry.core import api_token

    accounts = api_token.codex_sandbox_accounts()
    if not accounts:
        return []
    path = api_token.ingest_token_path()
    try:
        api_token.ensure_ingest_token(path)
    except OSError as exc:
        logger.warning("Codex sandbox: could not write the ingest-only token (%s)", exc)
        return []
    granted = api_token.grant_read(path, accounts)
    if granted:
        logger.info("Codex sandbox accounts can now send events: %s", ", ".join(granted))
    else:
        logger.warning("Codex sandbox: could not grant %s read on %s", ", ".join(accounts), path)
    return granted


# --- GitHub Copilot (CLI and VS Code agent mode, ~/.copilot/hooks/) -----------
# One file serves both. Copilot CLI reads every *.json in ~/.copilot/hooks (or
# $COPILOT_HOME/hooks), and VS Code's Local harness reads the same directory and
# accepts the CLI's format, detected by its `version` field: lowerCamel event
# names, mapped to its own, and `bash` / `powershell` command fields, mapped to
# its per-OS commands (microsoft/vscode `hookSchema.ts`, `hookTypes.ts`).
#
# The file is ours alone, so it is written whole rather than merged: a user's own
# hooks live in their own files beside it, and Copilot loads them all.
#
# The PowerShell form needs `&`. VS Code on Windows runs a hook through
# `powershell -Command`, where a command that starts with a quoted path is a
# string expression, not a call. Without the call operator the hook would exit
# non-zero, which VS Code treats as a non-blocking error: nothing recorded and
# every deny an allow.
COPILOT_HOOK_FILE = "agentmetry.json"

#: (Copilot's event key, the PascalCase name our mapper and enforcement key on).
#: `permissionRequest` is CLI-only and VS Code does not map it; `preToolUse` is
#: the gate on both.
COPILOT_HOOK_EVENTS: tuple[tuple[str, str], ...] = (
    ("sessionStart", "SessionStart"),
    ("userPromptSubmitted", "UserPromptSubmit"),
    ("preToolUse", "PreToolUse"),
    ("postToolUse", "PostToolUse"),
    ("sessionEnd", "SessionEnd"),
    ("agentStop", "Stop"),
)


def copilot_hooks_dir() -> Path:
    home = os.environ.get("COPILOT_HOME", "").strip()
    return (Path(home).expanduser() if home else user_profile_dir() / ".copilot") / "hooks"


def copilot_hooks_document(
    *, python: str | None = None, ingest: Path | None = None, repo_root: Path | None = None
) -> dict[str, Any]:
    """The whole hooks file, in Copilot CLI's version-1 format."""
    hooks: dict[str, Any] = {}
    for key, event in COPILOT_HOOK_EVENTS:
        command = hook_command("copilot", event, python=python, ingest=ingest, repo_root=repo_root)
        hooks[key] = [
            {
                "type": "command",
                "bash": command,
                "powershell": f"& {command}",
                "timeoutSec": 10,
            }
        ]
    return {"version": 1, "hooks": hooks}


def install_copilot_global_hooks(
    *, repo_root: Path | None = None, python: str | None = None
) -> Path | None:
    """Write ~/.copilot/hooks/agentmetry.json for Copilot CLI and VS Code agent mode.

    Not called from `bootstrap_tier_b_hooks`. VS Code's hooks are a preview
    feature an organisation can switch off, so a silent install could look like
    coverage that is not there; installing is a decision `hooks install` makes.
    """
    root = repo_root or _repo_root()
    if hook_target(root) == "none":
        logger.warning("Copilot hook bootstrap skipped: no way to reach ingest from %s", root)
        return None
    doc = copilot_hooks_document(
        python=python or sys.executable, ingest=_ingest_script(root), repo_root=root
    )
    hooks_dir = copilot_hooks_dir()
    hooks_dir.mkdir(parents=True, exist_ok=True)
    path = hooks_dir / COPILOT_HOOK_FILE
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    logger.info("Installed global Copilot audit hooks -> %s", path)
    return path


def _kimi_config_dir() -> Path:
    home = os.environ.get("KIMI_CODE_HOME", "").strip()
    if home:
        return Path(home).expanduser()
    return user_profile_dir() / ".kimi-code"


def kimi_hooks_toml_block(*, python: str, ingest: Path, repo_root: Path | None = None) -> str:
    lines = [
        KIMI_HOOKS_BEGIN,
        "# Managed by Agentmetry — re-run scripts/install_kimi_hooks.ps1 to update",
    ]
    for event in FAMILY_HOOK_EVENTS:
        cmd = _family_command("kimi", event, python=python, ingest=ingest, repo_root=repo_root)
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
    if hook_target(root) == "none":
        # No checkout, no frozen binary, no console script: nothing a hook
        # could invoke. Writing a config here would look like coverage.
        logger.warning(
            "Kimi hook bootstrap skipped: no way to reach ingest from %s", root
        )
        return None

    py = python or sys.executable
    config_dir = _kimi_config_dir()
    config_path = config_dir / "config.toml"
    block = kimi_hooks_toml_block(python=py, ingest=ingest, repo_root=root)

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
        "codex": install_codex_global_hooks,
        "copilot": install_copilot_global_hooks,
    }
    fn = installers.get(target, bootstrap_tier_b_hooks)
    if target in ("qwen", "kimi", "qoder", "codebuddy", "codex", "copilot"):
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
