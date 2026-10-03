"""Hooks in each vendor's admin-managed location (pilot hardening item 26).

`agentmetry hooks install` writes per-user configs (`~/.claude/settings.json`,
`~/.cursor/hooks.json`, `~/.codex/hooks.json`). A developer owns those files
and can delete the hooks; the heartbeat then reports the machine degraded, but
removal is one edit away. Each vendor also reads a machine-wide location that
only an administrator can write. Hooks placed there run for every user and
survive anything the user does to their own config:

- Claude Code: a drop-in in `managed-settings.d/` next to
  `managed-settings.json` (Windows `C:\\Program Files\\ClaudeCode`, macOS
  `/Library/Application Support/ClaudeCode`, Linux `/etc/claude-code`). Managed
  settings sit above every other level. `allowManagedHooksOnly` (opt-in here)
  also stops user and project hooks from running.
- Cursor: the enterprise `hooks.json` (Windows `C:\\ProgramData\\Cursor`,
  macOS `/Library/Application Support/Cursor`, Linux `/etc/cursor`). Hooks
  from every level run, enterprise first.
- Codex: `requirements.toml` (Windows `%ProgramData%\\OpenAI\\Codex`, else
  `/etc/codex`), `[[hooks.<Event>]]` entries; `allow_managed_hooks_only`
  (opt-in) skips user, project and plugin hooks.

Paths and keys are from the vendors' documentation as of 2026-10. Two of these
files are shared with whatever else an organisation manages, so every write
merges: other entries survive, ours are replaced, and the result is parsed
again before it is written. A Claude managed-settings document that does not
parse stops Claude Code from starting, which is the worst thing a recorder
could do to a developer.
"""

from __future__ import annotations

import json
import os
import sys
import tomllib
from pathlib import Path
from typing import Any

from agentmetry.core.audit import hook_bootstrap as hb

MANAGED_AGENTS = ("claude", "cursor", "codex")
CLAUDE_DROPIN = "50-agentmetry.json"
CODEX_BEGIN = "# agentmetry managed hooks begin (written by `agentmetry hooks install --managed`)"
CODEX_END = "# agentmetry managed hooks end"


def _program_data() -> Path:
    return Path(os.environ.get("ProgramData") or r"C:\ProgramData")


def claude_managed_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("ProgramFiles") or r"C:\Program Files") / "ClaudeCode"
    if sys.platform == "darwin":
        return Path("/Library/Application Support/ClaudeCode")
    return Path("/etc/claude-code")


def cursor_enterprise_hooks() -> Path:
    if sys.platform == "win32":
        return _program_data() / "Cursor" / "hooks.json"
    if sys.platform == "darwin":
        return Path("/Library/Application Support/Cursor/hooks.json")
    return Path("/etc/cursor/hooks.json")


def codex_requirements() -> Path:
    if sys.platform == "win32":
        return _program_data() / "OpenAI" / "Codex" / "requirements.toml"
    return Path("/etc/codex/requirements.toml")


def managed_paths() -> dict[str, Path]:
    return {
        "claude": claude_managed_dir() / "managed-settings.d" / CLAUDE_DROPIN,
        "cursor": cursor_enterprise_hooks(),
        "codex": codex_requirements(),
    }


def _command(app: str, event: str) -> str:
    return hb.hook_command(app, event)


def _is_ours(command: str, app: str) -> bool:
    return any(t in command for t in hb.HOOK_COMMAND_TOKENS) and app in command.split()


# --- documents ---------------------------------------------------------------


def claude_document(*, lock: bool = False) -> dict[str, Any]:
    """The whole drop-in. It is ours alone, so it is written, not merged."""
    doc: dict[str, Any] = {"hooks": {}}
    hb.merge_claude_hooks(doc, python=sys.executable, ingest=hb._ingest_script())
    if lock:
        doc["allowManagedHooksOnly"] = True
    return doc


def merge_cursor_document(existing: dict[str, Any]) -> dict[str, Any]:
    doc = dict(existing) if isinstance(existing, dict) else {}
    doc.setdefault("version", 1)
    hooks = doc.get("hooks") if isinstance(doc.get("hooks"), dict) else {}
    for event in hb.CURSOR_HOOK_EVENTS:
        entries = hooks.get(event) if isinstance(hooks.get(event), list) else []
        kept = [e for e in entries if not (isinstance(e, dict) and _is_ours(str(e.get("command", "")), "cursor"))]
        kept.append({"command": _command("cursor", event)})
        hooks[event] = kept
    doc["hooks"] = hooks
    return doc


def _toml_string(value: str) -> str:
    # A JSON string literal is a valid TOML basic string for anything a
    # command line contains: quotes and backslashes come out escaped.
    return json.dumps(value)


def codex_block() -> str:
    lines = [CODEX_BEGIN]
    for event, matcher in hb.CODEX_HOOK_EVENTS:
        command = _command("codex", event)
        lines.append(f"[[hooks.{event}]]")
        if matcher:
            lines.append(f"matcher = {_toml_string(matcher)}")
        lines.append(f"[[hooks.{event}.hooks]]")
        lines.append('type = "command"')
        lines.append(f"command = {_toml_string(command)}")
        if sys.platform == "win32":
            lines.append(f"command_windows = {_toml_string(command)}")
        lines.append("timeout = 10")
        lines.append(f"statusMessage = {_toml_string('Agentmetry ' + event)}")
        lines.append("")
    lines.append(CODEX_END)
    return "\n".join(lines) + "\n"


def merge_codex_requirements(text: str, *, lock: bool = False) -> str:
    """Replace our marked block in requirements.toml; leave everything else alone.

    The lock is a top-level key, and TOML requires top-level keys before the
    first table, so it is placed at the very top, and only if the file does not
    already decide it. `[features] hooks = true` is added only to a file with no
    `[features]` table: editing someone else's table in place is how a merge
    turns into a corrupted policy.
    """
    if CODEX_BEGIN in text and CODEX_END in text:
        head, rest = text.split(CODEX_BEGIN, 1)
        _, tail = rest.split(CODEX_END, 1)
        text = head.rstrip("\n") + "\n" + tail.lstrip("\n")
    current = tomllib.loads(text) if text.strip() else {}
    prefix = ""
    if lock and "allow_managed_hooks_only" not in current:
        prefix += "allow_managed_hooks_only = true\n"
    if lock and "features" not in current:
        prefix += "\n[features]\nhooks = true\n"
    body = (prefix + "\n" + text.strip("\n") + "\n") if prefix else (text.strip("\n") + "\n" if text.strip() else "")
    merged = body.rstrip("\n") + "\n\n" + codex_block()
    tomllib.loads(merged)  # raises before anything is written
    return merged.lstrip("\n")


# --- install -----------------------------------------------------------------


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".agentmetry-tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def install(agent: str, *, lock: bool = False) -> Path:
    """Write one agent's managed hooks. Raises on anything that would not parse."""
    if hb.hook_target() == "none":
        raise RuntimeError("no way to reach ingest from here; a managed hook would run nothing")
    path = managed_paths()[agent]
    if agent == "claude":
        text = json.dumps(claude_document(lock=lock), indent=2) + "\n"
        json.loads(text)
    elif agent == "cursor":
        existing: dict[str, Any] = {}
        if path.is_file():
            loaded = json.loads(path.read_text(encoding="utf-8"))  # unparseable: raise, never clobber
            if not isinstance(loaded, dict):
                raise ValueError(f"{path} is not a JSON object; refusing to overwrite it")
            existing = loaded
        text = json.dumps(merge_cursor_document(existing), indent=2) + "\n"
    elif agent == "codex":
        current = path.read_text(encoding="utf-8") if path.is_file() else ""
        text = merge_codex_requirements(current, lock=lock)
    else:
        raise ValueError(f"no managed location for {agent}")
    _write(path, text)
    return path


def status(agent: str) -> str:
    """'managed', 'absent', or 'broken' (present but unparseable or missing our hooks)."""
    path = managed_paths()[agent]
    if not path.is_file():
        return "absent"
    try:
        raw = path.read_text(encoding="utf-8")
        if agent == "codex":
            tomllib.loads(raw)
        else:
            json.loads(raw)
    except (OSError, ValueError):
        return "broken"
    return "managed" if any(t in raw for t in hb.HOOK_COMMAND_TOKENS) and agent in raw else "broken"
