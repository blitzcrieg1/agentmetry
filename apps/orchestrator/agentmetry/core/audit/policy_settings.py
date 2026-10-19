"""The five settings DLP and tool policy read, without importing pydantic (#171).

The hook runs in front of every tool call, and on a blocking hook the agent waits
for it. The DLP scanner and the tool-policy evaluator used to import
`core.config` to learn a mode and a manifest path each, and that one import
pulled in pydantic and pydantic-settings: about 220 ms of a 626 ms hook, paid on
every tool call to read five values.

So there are two ways to get them, and one answer:

* Where `core.config` is already loaded, the orchestrator and the test suite,
  the real `settings` object is read. A test that monkeypatches
  `settings.dlp_mode` still changes what the scanner sees.
* Where it is not, the hook, they are resolved here the way `Settings` resolves
  them: environment first, matched case-insensitively, then the orchestrator's
  `.env`, then the same defaults. `test_hook_import_cost.py` checks the two
  agree.

Standard library only. That is the whole point of the module.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

_HERE = Path(__file__).resolve()
_PACKAGE_ROOT = _HERE.parents[2]       # agentmetry/, as config._PACKAGE_ROOT


def env_path() -> Path:
    """The `.env` Settings reads (core/paths.py)."""
    from agentmetry.core.paths import env_file

    return env_file()

#: pydantic's own boolean vocabulary, so `AGENTMETRY_DLP_PII=off` means the same
#: thing to the hook as to the orchestrator.
_TRUE = frozenset({"1", "on", "t", "true", "y", "yes"})
_FALSE = frozenset({"0", "off", "f", "false", "n", "no"})

_DOTENV_CACHE: tuple[tuple[str, float, int] | None, dict[str, str]] = (None, {})


@dataclass(frozen=True)
class PolicySettings:
    dlp_mode: str
    dlp_rules_path: Path
    dlp_pii: bool
    tool_policy_mode: str
    tool_policy_path: Path


def _defaults() -> PolicySettings:
    policies = _PACKAGE_ROOT / "policies"
    return PolicySettings(
        dlp_mode="log",
        dlp_rules_path=policies / "dlp" / "manifest.yaml",
        dlp_pii=True,
        tool_policy_mode="log",
        tool_policy_path=policies / "tool" / "manifest.yaml",
    )


def _parse_dotenv(text: str) -> dict[str, str]:
    """The subset of python-dotenv that a `.env` for this project uses.

    `export` prefixes, single or double quotes, and a ` #` comment after an
    unquoted value. Keys are lowercased, because Settings matches them
    case-insensitively.
    """
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        out[key.strip().lower()] = value
    return out


def _dotenv() -> dict[str, str]:
    """The orchestrator's `.env`, parsed once per change to the file."""
    global _DOTENV_CACHE
    path = env_path()
    try:
        stat = path.stat()
    except OSError:
        return {}
    stamp = (str(path), stat.st_mtime, stat.st_size)
    if _DOTENV_CACHE[0] == stamp:
        return _DOTENV_CACHE[1]
    try:
        parsed = _parse_dotenv(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return {}
    _DOTENV_CACHE = (stamp, parsed)
    return parsed


def _lookup(name: str, environ: dict[str, str], dotenv: dict[str, str]) -> str | None:
    # Present-but-empty counts as set, as it does for Settings (env_ignore_empty
    # is off): an empty mode is not "use the default".
    key = name.lower()
    if key in environ:
        return environ[key]
    return dotenv.get(key)


def _bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    text = raw.strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    # Settings refuses to start on this. The hook must not fail a tool call over
    # a typo, so it keeps the default and the orchestrator's error stays the
    # place the operator finds out.
    return default


def _as_text(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _locked_and_user(key: str) -> tuple[object, object]:
    """Managed lock and user-file value. Imported lazily: the hook pays for it
    on the first scan, not at import, and a missing module must not break a call."""
    from agentmetry.core.managed_policy import locked_value, user_value

    return locked_value(key), user_value(key)


def resolve() -> PolicySettings:
    """Resolve without pydantic, as the hook does.

    A managed lock wins over the environment and over `~/.agentmetry/policy.yaml`.
    The user file fills a key only when the environment and `.env` did not.
    """
    environ = {k.lower(): v for k, v in os.environ.items()}
    dotenv = _dotenv()
    base = _defaults()

    def text(name: str, default: str, key: str | None = None) -> str:
        if key is not None:
            locked, user = _locked_and_user(key)
            if locked is not None:
                return _as_text(locked)
        else:
            user = None
        value = _lookup(name, environ, dotenv)
        if value is not None:
            return value
        if key is not None and user is not None:
            return _as_text(user)
        return default

    def flag(name: str, default: bool, key: str) -> bool:
        locked, user = _locked_and_user(key)
        if locked is not None:
            return bool(locked) if isinstance(locked, bool) else _bool(_as_text(locked), default)
        raw = _lookup(name, environ, dotenv)
        if raw is not None:
            return _bool(raw, default)
        if user is not None:
            return bool(user) if isinstance(user, bool) else _bool(_as_text(user), default)
        return default

    def path(name: str, default: Path) -> Path:
        value = _lookup(name, environ, dotenv)
        return default if value is None else Path(value)

    return PolicySettings(
        dlp_mode=text("AGENTMETRY_DLP_MODE", base.dlp_mode, "dlp_mode"),
        dlp_rules_path=path("AGENTMETRY_DLP_RULES_PATH", base.dlp_rules_path),
        dlp_pii=flag("AGENTMETRY_DLP_PII", base.dlp_pii, "dlp_pii"),
        tool_policy_mode=text("AGENTMETRY_TOOL_POLICY_MODE", base.tool_policy_mode, "tool_policy_mode"),
        tool_policy_path=path("AGENTMETRY_TOOL_POLICY_PATH", base.tool_policy_path),
    )


def _with_locks(base: PolicySettings) -> PolicySettings:
    """Managed locks win over the already-loaded Settings object."""
    dlp_mode, _user = _locked_and_user("dlp_mode")
    dlp_pii, _user_pii = _locked_and_user("dlp_pii")
    tool_mode, _user_tool = _locked_and_user("tool_policy_mode")
    if dlp_mode is None and dlp_pii is None and tool_mode is None:
        return base
    return PolicySettings(
        dlp_mode=_as_text(dlp_mode) if dlp_mode is not None else base.dlp_mode,
        dlp_rules_path=base.dlp_rules_path,
        dlp_pii=bool(dlp_pii) if isinstance(dlp_pii, bool) else (
            _bool(_as_text(dlp_pii), base.dlp_pii) if dlp_pii is not None else base.dlp_pii
        ),
        tool_policy_mode=_as_text(tool_mode) if tool_mode is not None else base.tool_policy_mode,
        tool_policy_path=base.tool_policy_path,
    )


def policy_settings() -> PolicySettings:
    """The settings, from the loaded `Settings` object when there is one."""
    config = sys.modules.get("agentmetry.core.config")
    settings = getattr(config, "settings", None) if config is not None else None
    if settings is None:
        return resolve()
    return _with_locks(PolicySettings(
        dlp_mode=settings.dlp_mode,
        dlp_rules_path=Path(settings.dlp_rules_path),
        dlp_pii=bool(settings.dlp_pii),
        tool_policy_mode=settings.tool_policy_mode,
        tool_policy_path=Path(settings.tool_policy_path),
    ))
