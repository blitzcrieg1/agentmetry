"""How the agents on this machine are configured to ask, or not ask, before acting.

Coverage says whether our hook is installed. The trail says what an agent did.
Neither says that Claude Code on this laptop starts every session in
`bypassPermissions`, that Codex runs with `approval_policy = "never"` and no
sandbox, or that VS Code approves every tool call. Those settings are where the
risk of a coding agent is decided, they live in files the agent reads at start,
and an EDR does not model them. This reads them.

Like `mcp_inventory`, this inspects configuration at rest, so it is a
diagnostic, not a detection rule, and it needs nothing from the sequence engine.

## Only settings the vendors document

Every check names a setting from the vendor's own reference, checked 2026-10-13:

* Claude Code: `permissions.defaultMode`, `permissions.allow`,
  `enableAllProjectMcpServers`, `disableAllHooks`,
  `skipDangerousModePermissionPrompt`, and the managed
  `permissions.disableBypassPermissionsMode`
  (code.claude.com/docs/en/settings-reference).
* Codex: `approval_policy`, `sandbox_mode`, `features.hooks`, in
  `config.toml` and `<name>.config.toml` profile files
  (learn.chatgpt.com/docs/config-file/config-reference).
* VS Code agent mode: `chat.tools.global.autoApprove`,
  `chat.permissions.default`, `chat.tools.terminal.autoApprove`,
  `chat.tools.edits.autoApprove`, `chat.useHooks`, `chat.mcp.discovery.enabled`
  (code.visualstudio.com/docs/copilot/reference/copilot-settings).
* Copilot CLI: `disableAllHooks` (docs.github.com, hooks reference).

Cursor keeps its auto-run setting in an editor state database rather than a
settings file, and nothing here reads it. It is reported as not checked rather
than as clean, because "no findings" for an agent nobody looked at would be a
claim this module cannot make.

## What a finding means

A finding is a setting that removes a human or a hook from the path between the
agent and an action. It is not evidence of misuse: plenty of developers run
`bypassPermissions` in a container on purpose. The claim is "this machine is
configured so that X happens without asking", never "this machine is
compromised".
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentmetry.core.paths import named_user_profile, user_profile_dir

HIGH = "high"
MEDIUM = "medium"
LOW = "low"
_SEVERITY_ORDER = {HIGH: 0, MEDIUM: 1, LOW: 2}

#: Agents whose configuration this module does not read, and why.
NOT_CHECKED = {
    "cursor": "auto-run lives in Cursor's editor state database, not a settings file",
}


@dataclass(frozen=True)
class Finding:
    agent: str
    #: `user`, `project`, `managed`, `profile:<name>` or `hooks-file`. A label,
    #: never a path, so an emitted finding carries no home directory or username.
    scope: str
    setting: str
    value: str
    severity: str
    why: str

    def wire(self) -> dict[str, str]:
        return {
            "agent": self.agent, "scope": self.scope, "setting": self.setting,
            "value": self.value, "severity": self.severity,
        }


@dataclass
class Posture:
    findings: list[Finding] = field(default_factory=list)
    files_read: list[Path] = field(default_factory=list)
    unreadable: list[Path] = field(default_factory=list)

    def sorted(self) -> list[Finding]:
        return sorted(
            self.findings,
            key=lambda f: (_SEVERITY_ORDER.get(f.severity, 9), f.agent, f.scope, f.setting),
        )

    def counts(self) -> dict[str, int]:
        out = {HIGH: 0, MEDIUM: 0, LOW: 0}
        for f in self.findings:
            out[f.severity] = out.get(f.severity, 0) + 1
        return out

    def digest(self) -> str:
        """Changes when a finding appears, goes or changes value. Order-free."""
        rows = sorted(json.dumps(f.wire(), sort_keys=True) for f in self.findings)
        return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


# --- reading ------------------------------------------------------------------


def _strip_jsonc(text: str) -> str:
    """VS Code settings are JSON with comments and trailing commas."""
    out: list[str] = []
    i, n, in_str = 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(c)
            i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def _load(path: Path, posture: Posture, *, kind: str = "json") -> dict[str, Any] | None:
    try:
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8-sig")
        if kind == "toml":
            data: Any = tomllib.loads(text)
        elif kind == "jsonc":
            data = json.loads(_strip_jsonc(text) or "{}")
        else:
            data = json.loads(text or "{}")
    except (OSError, ValueError):
        posture.unreadable.append(path)
        return None
    posture.files_read.append(path)
    return data if isinstance(data, dict) else None


# --- Claude Code --------------------------------------------------------------

_SHELL_WILDCARDS = frozenset({"Bash", "Bash(*)", "PowerShell", "PowerShell(*)"})


def _claude_managed_settings() -> Path:
    from agentmetry.core.audit.managed_hooks import claude_managed_dir

    return claude_managed_dir() / "managed-settings.json"


def _check_claude(posture: Posture, project: Path | None) -> None:
    files: list[tuple[str, Path]] = [("user", user_profile_dir() / ".claude" / "settings.json")]
    if project is not None:
        files += [
            ("project", project / ".claude" / "settings.json"),
            ("project", project / ".claude" / "settings.local.json"),
        ]
    managed = _load(_claude_managed_settings(), posture)
    bypass_disabled = bool(
        managed
        and isinstance(managed.get("permissions"), dict)
        and managed["permissions"].get("disableBypassPermissionsMode") == "disable"
    )
    docs = [(scope, _load(path, posture)) for scope, path in files]
    if managed is not None:
        docs.append(("managed", managed))

    for scope, doc in docs:
        if not doc:
            continue
        perms = doc.get("permissions") if isinstance(doc.get("permissions"), dict) else {}
        mode = perms.get("defaultMode")
        if mode == "bypassPermissions":
            if bypass_disabled:
                posture.findings.append(Finding(
                    "claude", scope, "permissions.defaultMode", mode, LOW,
                    "set, but managed settings disable bypassPermissions, so it has no effect",
                ))
            elif scope == "project":
                posture.findings.append(Finding(
                    "claude", scope, "permissions.defaultMode", mode, MEDIUM,
                    "every tool call runs without asking; from project settings this "
                    "takes effect only on Claude Code before v2.1.257",
                ))
            else:
                posture.findings.append(Finding(
                    "claude", scope, "permissions.defaultMode", mode, HIGH,
                    "every session starts running every tool call without asking",
                ))
        elif mode == "auto":
            posture.findings.append(Finding(
                "claude", scope, "permissions.defaultMode", mode, LOW,
                "sessions run without routine prompts; a classifier checks shell and "
                "network actions instead of a person",
            ))
        allow = perms.get("allow") if isinstance(perms.get("allow"), list) else []
        for rule in allow:
            if str(rule).strip() in _SHELL_WILDCARDS:
                posture.findings.append(Finding(
                    "claude", scope, "permissions.allow", str(rule).strip(), HIGH,
                    "every shell command is pre-approved",
                ))
        if doc.get("enableAllProjectMcpServers") is True:
            posture.findings.append(Finding(
                "claude", scope, "enableAllProjectMcpServers", "true", MEDIUM,
                "every server in a project's .mcp.json is approved without a prompt, "
                "and a stdio server is a command that runs as the developer",
            ))
        if doc.get("disableAllHooks") is True and scope != "managed":
            posture.findings.append(Finding(
                "claude", scope, "disableAllHooks", "true", HIGH,
                "hooks are off, so Agentmetry records nothing from Claude Code here "
                "unless its hooks are managed",
            ))
        if doc.get("skipDangerousModePermissionPrompt") is True and not bypass_disabled:
            posture.findings.append(Finding(
                "claude", scope, "skipDangerousModePermissionPrompt", "true", MEDIUM,
                "bypassPermissions starts without its confirmation; Claude Code writes "
                "this once someone has accepted that prompt",
            ))


# --- Codex --------------------------------------------------------------------


def _codex_home() -> Path:
    home = os.environ.get("CODEX_HOME", "").strip()
    return Path(home).expanduser() if home else user_profile_dir() / ".codex"


def _check_codex_doc(posture: Posture, scope: str, doc: dict[str, Any]) -> None:
    approval = doc.get("approval_policy")
    sandbox = doc.get("sandbox_mode")
    if approval == "never":
        posture.findings.append(Finding(
            "codex", scope, "approval_policy", "never", HIGH,
            "Codex never stops to ask before acting",
        ))
    if sandbox == "danger-full-access":
        posture.findings.append(Finding(
            "codex", scope, "sandbox_mode", "danger-full-access", HIGH,
            "commands run with no sandbox, with the developer's full access",
        ))
    features = doc.get("features") if isinstance(doc.get("features"), dict) else {}
    if features.get("hooks") is False:
        posture.findings.append(Finding(
            "codex", scope, "features.hooks", "false", HIGH,
            "hooks are off, so Agentmetry records nothing from Codex here",
        ))


def _check_codex(posture: Posture, project: Path | None) -> None:
    home = _codex_home()
    doc = _load(home / "config.toml", posture, kind="toml")
    if doc:
        _check_codex_doc(posture, "user", doc)
    try:
        profiles = sorted(home.glob("*.config.toml")) if home.is_dir() else []
    except OSError:
        profiles = []
    for path in profiles:
        pdoc = _load(path, posture, kind="toml")
        if pdoc:
            _check_codex_doc(posture, f"profile:{path.name[: -len('.config.toml')]}", pdoc)
    if project is not None:
        pdoc = _load(project / ".codex" / "config.toml", posture, kind="toml")
        if pdoc:
            _check_codex_doc(posture, "project", pdoc)


# --- VS Code (Copilot agent mode) ----------------------------------------------

#: Terminal auto-approve keys that match every command.
_BROAD_TERMINAL = frozenset({"/.*/", "/.+/", "/^.*$/", "/^.+$/", "*"})
_BROAD_EDITS = frozenset({"**", "**/*", "*"})


def vscode_user_settings() -> list[Path]:
    """Stable and Insiders user settings, where each OS keeps them.

    `APPDATA` and `XDG_CONFIG_HOME` belong to the process's own account. Under a
    service told whose home to read, they name the service's profile, so they
    are ignored and the developer's default location is used.
    """
    names = ("Code", "Code - Insiders")
    home = user_profile_dir()
    own_env = not named_user_profile()
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA") if own_env else None
        base = Path(appdata) if appdata else home / "AppData" / "Roaming"
    elif sys.platform == "darwin":
        base = home / "Library" / "Application Support"
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME") if own_env else None
        base = Path(xdg) if xdg else home / ".config"
    return [base / name / "User" / "settings.json" for name in names]


def _check_vscode_doc(posture: Posture, scope: str, doc: dict[str, Any]) -> None:
    if doc.get("chat.tools.global.autoApprove") is True:
        posture.findings.append(Finding(
            "copilot", scope, "chat.tools.global.autoApprove", "true", HIGH,
            "every agent tool call is approved without asking; VS Code warns it "
            "disables critical security protections",
        ))
    default = doc.get("chat.permissions.default")
    if default in ("autoApprove", "autopilot"):
        posture.findings.append(Finding(
            "copilot", scope, "chat.permissions.default", str(default), HIGH,
            "new agent sessions start with auto-approval",
        ))
    terminal = doc.get("chat.tools.terminal.autoApprove")
    if isinstance(terminal, dict):
        for key, value in terminal.items():
            if value is True and str(key).strip() in _BROAD_TERMINAL:
                posture.findings.append(Finding(
                    "copilot", scope, "chat.tools.terminal.autoApprove", str(key), HIGH,
                    "a rule that matches every terminal command approves all of them",
                ))
    edits = doc.get("chat.tools.edits.autoApprove")
    if isinstance(edits, dict):
        for key, value in edits.items():
            if value is True and str(key).strip() in _BROAD_EDITS:
                posture.findings.append(Finding(
                    "copilot", scope, "chat.tools.edits.autoApprove", str(key), MEDIUM,
                    "edits to every file are approved without review",
                ))
    if doc.get("chat.useHooks") is False:
        posture.findings.append(Finding(
            "copilot", scope, "chat.useHooks", "false", HIGH,
            "agent hooks are off in VS Code, so Agentmetry records nothing from its "
            "agent mode here",
        ))
    if doc.get("chat.mcp.discovery.enabled") is True:
        posture.findings.append(Finding(
            "copilot", scope, "chat.mcp.discovery.enabled", "true", LOW,
            "MCP servers configured for other apps are imported into VS Code",
        ))


def _check_vscode(posture: Posture, project: Path | None) -> None:
    for path in vscode_user_settings():
        doc = _load(path, posture, kind="jsonc")
        if doc:
            _check_vscode_doc(posture, "user", doc)
    if project is not None:
        doc = _load(project / ".vscode" / "settings.json", posture, kind="jsonc")
        if doc:
            _check_vscode_doc(posture, "project", doc)


# --- Copilot CLI ---------------------------------------------------------------


def _check_copilot_cli(posture: Posture) -> None:
    from agentmetry.core.audit.hook_bootstrap import COPILOT_HOOK_FILE, copilot_hooks_dir

    hooks_dir = copilot_hooks_dir()
    settings = _load(hooks_dir.parent / "settings.json", posture)
    if settings and settings.get("disableAllHooks") is True:
        posture.findings.append(Finding(
            "copilot", "user", "disableAllHooks", "true", HIGH,
            "Copilot CLI skips every hook except policy hooks, so Agentmetry records "
            "nothing from it here unless its hooks are managed",
        ))
    ours = _load(hooks_dir / COPILOT_HOOK_FILE, posture)
    if ours and ours.get("disableAllHooks") is True:
        posture.findings.append(Finding(
            "copilot", "hooks-file", "disableAllHooks", "true", HIGH,
            "set inside Agentmetry's own hooks file, which turns exactly those hooks off",
        ))


# --- entry points ----------------------------------------------------------------


def collect(project: Path | None = None) -> Posture:
    """Read every agent's settings this module knows. Never raises on a bad file."""
    posture = Posture()
    _check_claude(posture, project)
    _check_codex(posture, project)
    _check_vscode(posture, project)
    _check_copilot_cli(posture)
    return posture


def summary_lines(posture: Posture) -> list[str]:
    counts = posture.counts()
    lines = [
        f"Agent posture: {counts[HIGH]} high, {counts[MEDIUM]} medium, {counts[LOW]} low "
        f"({len(posture.files_read)} settings file(s) read)",
    ]
    for f in posture.sorted():
        lines.append(f"  [{f.severity}] {f.agent} {f.scope}: {f.setting} = {f.value}")
        lines.append(f"      {f.why}")
    for path in posture.unreadable:
        lines.append(f"  could not parse {path}")
    for agent, why in NOT_CHECKED.items():
        lines.append(f"  not checked: {agent} ({why})")
    return lines
