"""Managed policy hierarchy. Standard library only.

A fleet file locks the keys it sets. A developer file and the process
environment fill everything else, and neither can change a locked key.
A solo install has no managed file, so nothing here changes a default.

Sources, highest first:

1. Platform managed policy, which is honored only when it is not user-writable:
   macOS `/Library/Managed Preferences/ai.agentmetry.sensor.plist` and
   `/etc/agentmetry/policy.yaml` (root-owned, not group or world writable,
   no symlink on the path); Windows `HKLM\\SOFTWARE\\Policies\\Agentmetry`
   and `%ProgramData%\\Agentmetry\\policy.yaml` (SYSTEM or Administrators
   write, nobody else); Linux `/etc/agentmetry/policy.yaml` under the same
   POSIX rule. `AGENTMETRY_POLICY_DIR` (or `--policy-dir`) is an extra
   managed location, subject to the same check. A file that fails the check
   is refused whole. It is not reread as user policy.
2. The user file `<profile>/.agentmetry/policy.yaml`. No ownership check.
   This is the OSS config file.
3. The process environment and the orchestrator `.env`, which
   `policy_settings` and `Settings` already apply. This module only wins
   over them for locked keys.

The hook calls `load_policy` through `policy_settings`. That is a few stat
calls, cached on mtime, and it does not import pydantic.
"""

from __future__ import annotations

import os
import plistlib
import re
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agentmetry.core.paths import user_profile_dir

SCHEMA = 1

_ENUMS: dict[str, frozenset[str]] = {
    "dlp_mode": frozenset({"log", "block", "disable"}),
    "tool_policy_mode": frozenset({"log", "block", "disable"}),
}
# `audit_sink` is one mode or a comma-separated list. `both` and `all` are the
# short forms `parse_sink_modes` already accepts. Kept here so this module does
# not import the sink stack.
_SINK_MODES = frozenset({
    "file", "webhook", "elastic", "splunk", "chronicle", "sentinel", "both", "all",
})


@dataclass(frozen=True)
class KeySpec:
    """One lockable key: the settings attribute (if any) and its env var."""

    field: str
    env: str
    kind: str  # bool, int, str, path


#: Operational locks only. Secrets (API tokens, SIEM credentials, the hash
#: key) stay in the daemon environment, not in a mode-0644 policy file.
SPECS: dict[str, KeySpec] = {
    "dlp_mode": KeySpec("dlp_mode", "AGENTMETRY_DLP_MODE", "str"),
    "dlp_pii": KeySpec("dlp_pii", "AGENTMETRY_DLP_PII", "bool"),
    "tool_policy_mode": KeySpec("tool_policy_mode", "AGENTMETRY_TOOL_POLICY_MODE", "str"),
    "auth_disabled": KeySpec("auth_disabled", "AGENTMETRY_AUTH_DISABLED", "bool"),
    "trusted_hosts": KeySpec("trusted_hosts", "AGENTMETRY_TRUSTED_HOSTS", "str"),
    "audit_sink": KeySpec("audit_sink", "AGENTMETRY_AUDIT_SINK", "str"),
    "auto_install_hooks": KeySpec("auto_install_hooks", "AGENTMETRY_AUTO_INSTALL_HOOKS", "bool"),
    "data_dir": KeySpec("", "AGENTMETRY_DATA_DIR", "path"),
    "hook_spool_path": KeySpec("", "AGENTMETRY_HOOK_SPOOL_PATH", "path"),
    "heartbeat_seconds": KeySpec("", "AGENTMETRY_HEARTBEAT_SECONDS", "int"),
}

_DEFAULTS: dict[str, Any] = {
    "dlp_mode": "log",
    "dlp_pii": True,
    "tool_policy_mode": "log",
    "auth_disabled": False,
    "trusted_hosts": "",
    "audit_sink": "file",
    "auto_install_hooks": False,
}

_DATA_FILES = {
    "audit_export_path": "audit-forward.jsonl",
    "audit_db_path": "audit.db",
    "detection_live_db_path": "detection_live.db",
    "detection_disposition_db_path": "detection_disposition.db",
}

# icacls rights that let the holder change or remove the file.
_WRITE_RIGHTS = frozenset({
    "F", "M", "W", "D", "DC", "DE", "WD", "AD", "WA", "WEA", "GW", "GA", "WO", "WDAC",
})
_PRIVILEGED_OWNERS = frozenset({
    "nt authority\\system",
    "system",
    "builtin\\administrators",
    "administrators",
    "s-1-5-18",
    "*s-1-5-18",
    "s-1-5-32-544",
    "*s-1-5-32-544",
})
_RIGHT = re.compile(r"\(([A-Za-z0-9,]+)\)")


class PolicySyntax(ValueError):
    """A managed document that cannot be applied safely. The whole file is refused."""


@dataclass(frozen=True)
class Trust:
    trusted: bool
    reason: str


@dataclass(frozen=True)
class PolicySource:
    role: str  # managed or user
    location: str
    accepted: bool
    reason: str
    keys: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()


@dataclass
class PolicyLayers:
    locked: dict[str, Any] = field(default_factory=dict)
    user: dict[str, Any] = field(default_factory=dict)
    sources: list[PolicySource] = field(default_factory=list)

    @property
    def rejected(self) -> list[PolicySource]:
        return [s for s in self.sources if s.role == "managed" and not s.accepted]


def clear_cache() -> None:
    global _CACHE
    _CACHE = None


_CACHE: tuple[Any, PolicyLayers] | None = None


def user_policy_path() -> Path:
    return user_profile_dir() / ".agentmetry" / "policy.yaml"


def platform_managed_candidates() -> list[Path]:
    """Managed files to consider, in the order the first lock wins.

    Missing paths are included so the caller can skip them. A present file
    still has to pass `assess_trust`.
    """
    found: list[Path] = []
    if sys.platform == "darwin":
        found.append(Path("/Library/Managed Preferences/ai.agentmetry.sensor.plist"))
        found.append(Path("/etc/agentmetry/policy.yaml"))
    elif os.name == "nt":
        programdata = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        found.append(Path(programdata) / "Agentmetry" / "policy.yaml")
    else:
        found.append(Path("/etc/agentmetry/policy.yaml"))
    extra = os.environ.get("AGENTMETRY_POLICY_DIR", "").strip()
    if extra:
        root = Path(extra).expanduser()
        if root.suffix.lower() in {".yaml", ".yml", ".plist"}:
            found.append(root)
        else:
            found.append(root / "policy.yaml")
            found.append(root / "policy.plist")
    return found


def read_registry_policy() -> dict[str, Any] | None:
    """HKLM policy values, or None when there is no such key.

    HKLM is the trust anchor: a standard user cannot write it. Only Windows
    has the key. Other platforms return None without importing winreg.
    """
    if os.name != "nt":
        return None
    import winreg

    access = winreg.KEY_READ
    wow = getattr(winreg, "KEY_WOW64_64KEY", 0)
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Policies\Agentmetry", 0, access | wow
        )
    except OSError:
        return None
    values: dict[str, Any] = {}
    try:
        index = 0
        while True:
            try:
                name, raw, _kind = winreg.EnumValue(key, index)
            except OSError:
                break
            values[str(name)] = raw
            index += 1
    finally:
        winreg.CloseKey(key)
    return values


def judge_posix_chain(entries: list[tuple[str, int, int, bool]]) -> Trust:
    """Root-owned, not group or world writable, and not a symlink.

    `entries` is `(path, uid, mode, is_symlink)` from the filesystem root down
    to the file. A writable parent is enough to replace the file, so the file's
    own mode is not the check.
    """
    if not entries:
        return Trust(False, "empty path")
    for path, uid, mode, is_link in entries:
        if is_link:
            return Trust(False, f"symlink at {path} is not a managed policy")
        if uid != 0:
            return Trust(False, f"{path} owner uid {uid}, want root (0)")
        if mode & 0o022:
            return Trust(False, f"{path} is group or world writable")
    return Trust(True, "root-owned and not writable by group or other")


def posix_trust(path: Path) -> Trust:
    if not path.is_absolute():
        return Trust(False, "managed policy path must be absolute")
    entries: list[tuple[str, int, int, bool]] = []
    current = Path(path.anchor)
    try:
        st = current.lstat()
    except OSError as exc:
        return Trust(False, f"cannot stat {current}: {exc.strerror or exc}")
    entries.append((str(current), st.st_uid, stat.S_IMODE(st.st_mode), stat.S_ISLNK(st.st_mode)))
    for part in path.parts[1:]:
        current = current / part
        try:
            st = current.lstat()
        except OSError as exc:
            return Trust(False, f"cannot stat {current}: {exc.strerror or exc}")
        entries.append((str(current), st.st_uid, stat.S_IMODE(st.st_mode), stat.S_ISLNK(st.st_mode)))
    return judge_posix_chain(entries)


def _ace_from_line(line: str) -> tuple[str, set[str]] | None:
    """One icacls ACE, or None when the line is a filename or a summary.

    The principal is the last token, or the last two when they are
    `NT AUTHORITY\\SYSTEM` or `CREATOR OWNER`. A filename on the same line
    stays in front of that and is not the principal.
    """
    idx = line.rfind(":(")
    if idx == -1:
        return None
    rights = {token.group(1).upper() for token in _RIGHT.finditer(line[idx + 1:])}
    if not rights:
        return None
    parts = line[:idx].split()
    if not parts:
        return None
    if len(parts) >= 2 and parts[-2].upper() in {"NT", "BUILTIN", "CREATOR", "APPLICATION"}:
        principal = f"{parts[-2]} {parts[-1]}"
    else:
        principal = parts[-1]
    return principal.lower(), rights


def windows_trust_from_text(text: str) -> Trust:
    """Decide from `icacls` output. Write must belong only to SYSTEM or Administrators.

    Inherit-only ACEs (`IO`) apply to children created later, not to this
    object, so they do not make the file user-writable.
    """
    aces: list[tuple[str, set[str]]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.lower().startswith("successfully processed"):
            continue
        if line.lower().startswith("failed processing"):
            continue
        parsed = _ace_from_line(line)
        if parsed is None:
            continue
        principal, rights = parsed
        if "IO" in rights:
            continue
        aces.append((principal, rights))
    if not aces:
        return Trust(False, "no ACL entries could be read")
    for principal, rights in aces:
        if rights & _WRITE_RIGHTS and principal not in _PRIVILEGED_OWNERS:
            return Trust(False, f"{principal} can modify this managed policy")
    return Trust(True, "only SYSTEM or Administrators can modify this file")


def _icacls(path: Path) -> str:
    import subprocess

    out = subprocess.run(
        ["icacls", str(path)], capture_output=True, text=True, check=False, timeout=15
    )
    return (out.stdout or "") + (out.stderr or "")


def windows_trust(path: Path) -> Trust:
    if path.is_symlink():
        return Trust(False, f"symlink at {path} is not a managed policy")
    text = _icacls(path)
    file_verdict = windows_trust_from_text(text)
    if not file_verdict.trusted:
        return file_verdict
    parent = windows_trust_from_text(_icacls(path.parent))
    if not parent.trusted:
        return Trust(False, f"parent directory: {parent.reason}")
    return file_verdict


def assess_trust(path: Path) -> Trust:
    """Whether a managed file is safe to honor. Never raises."""
    try:
        if os.name == "nt":
            return windows_trust(path)
        return posix_trust(path)
    except (OSError, PolicySyntax) as exc:
        return Trust(False, f"could not check ownership: {exc}")


def _scalar(raw: str) -> Any:
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1]
    low = raw.lower()
    if low in {"true", "yes", "on"}:
        return True
    if low in {"false", "no", "off"}:
        return False
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    return raw


def parse_policy_yaml(text: str) -> dict[str, Any]:
    """The flat `key: value` subset a policy file is allowed to be.

    Nested maps and lists are refused. A policy that needs them is a program,
    and this loader is not a program runner. PyYAML stays off this path so the
    hook does not pay for it when it only needs five strings.
    """
    data: dict[str, Any] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("- ") or line.startswith("{") or line.startswith("["):
            raise PolicySyntax(f"line {lineno}: collections are not a policy")
        if ":" not in line:
            raise PolicySyntax(f"line {lineno}: expected key: value")
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not key or " " in key:
            raise PolicySyntax(f"line {lineno}: invalid key")
        if value in {"|", ">", "|-", ">-"} or value.startswith(("{", "[")):
            raise PolicySyntax(f"line {lineno}: nested values are not a policy")
        if key in data:
            raise PolicySyntax(f"line {lineno}: duplicate key {key}")
        data[key] = _scalar(value) if value else ""
    return data


def _unwrap_managed_plist(loaded: dict[str, Any]) -> dict[str, Any]:
    """Accept a flat domain plist or the Managed Preferences wrapper.

    macOS writes `/Library/Managed Preferences/ai.agentmetry.sensor.plist` as
    the preference keys themselves, or as `{domain: {Forced: [{mcx_preference_settings: ...}]}}`.
    Payload* keys from a configuration profile are not policy.
    """
    if any(key in SPECS for key in loaded):
        return {key: value for key, value in loaded.items() if not str(key).startswith("Payload")}
    for value in loaded.values():
        if not isinstance(value, dict):
            continue
        forced = value.get("Forced")
        if not isinstance(forced, list):
            continue
        for item in forced:
            settings = item.get("mcx_preference_settings") if isinstance(item, dict) else None
            if isinstance(settings, dict):
                return dict(settings)
    return {key: value for key, value in loaded.items() if not str(key).startswith("Payload")}


def parse_policy_plist(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        loaded = plistlib.load(fh)
    if not isinstance(loaded, dict):
        raise PolicySyntax("plist root must be a dictionary")
    return _unwrap_managed_plist(loaded)


def _coerce(key: str, value: Any) -> Any:
    spec = SPECS[key]
    if spec.kind == "bool":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        raise PolicySyntax(f"{key} is not a boolean")
    if spec.kind == "int":
        if isinstance(value, bool):
            raise PolicySyntax(f"{key} is not an integer")
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise PolicySyntax(f"{key} is not an integer") from exc
        if number < 0:
            raise PolicySyntax(f"{key} must be >= 0")
        return number
    if isinstance(value, bool):
        raise PolicySyntax(f"{key} must be a string")
    text = str(value).strip()
    allowed = _ENUMS.get(key)
    if allowed is not None and text not in allowed:
        raise PolicySyntax(f"{key} must be one of {', '.join(sorted(allowed))}")
    if key == "audit_sink":
        parts = [part.strip() for part in text.split(",") if part.strip()]
        bad = [part for part in parts if part not in _SINK_MODES]
        if not parts or bad:
            raise PolicySyntax(
                f"audit_sink must be one of {', '.join(sorted(_SINK_MODES))}, "
                "or a comma-separated list of those"
            )
        return ",".join(parts)
    if spec.kind == "path" and not text:
        raise PolicySyntax(f"{key} is empty")
    return text


def normalize_document(data: dict[str, Any]) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Split a parsed document into known values and unknown key names.

    An unknown key is ignored (forward compatible). A known key with a bad
    value refuses the whole document, so a typo cannot lock the other keys
    while silently dropping the one the admin cared about.
    """
    schema = data.get("schema", SCHEMA)
    try:
        schema_n = int(schema)
    except (TypeError, ValueError) as exc:
        raise PolicySyntax(f"schema {schema!r} is not a version") from exc
    if schema_n != SCHEMA:
        raise PolicySyntax(f"schema {schema_n} is not supported (want {SCHEMA})")
    values: dict[str, Any] = {}
    unknown: list[str] = []
    for key, raw in data.items():
        if key == "schema":
            continue
        if key not in SPECS:
            unknown.append(str(key))
            continue
        values[key] = _coerce(key, raw)
    return values, tuple(unknown)


def _read_document(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".plist":
        return parse_policy_plist(path)
    return parse_policy_yaml(path.read_text(encoding="utf-8"))


def _consider_file(path: Path, role: str, checker: Callable[[Path], Trust]) -> tuple[PolicySource, dict[str, Any]]:
    if not path.is_file():
        return PolicySource(role, str(path), False, "absent"), {}
    if role == "managed":
        verdict = checker(path)
        if not verdict.trusted:
            return PolicySource(role, str(path), False, verdict.reason), {}
        reason = verdict.reason
    else:
        reason = "user policy"
    try:
        values, unknown = normalize_document(_read_document(path))
    except (OSError, PolicySyntax, plistlib.InvalidFileException, ValueError) as exc:
        return PolicySource(role, str(path), False, str(exc)), {}
    return PolicySource(role, str(path), True, reason, tuple(values), unknown), values


def _stamp() -> tuple[Any, ...]:
    stats: list[tuple[str, int | None, int | None]] = []
    for path in platform_managed_candidates():
        try:
            st = path.stat()
            stats.append((str(path), st.st_mtime_ns, st.st_size))
        except OSError:
            stats.append((str(path), None, None))
    user = user_policy_path()
    try:
        st = user.stat()
        user_stat: tuple[Any, ...] = (str(user), st.st_mtime_ns, st.st_size)
    except OSError:
        user_stat = (str(user), None, None)
    registry = read_registry_policy() or {}
    reg_stamp = tuple(sorted((str(k), repr(v)) for k, v in registry.items()))
    return (tuple(stats), user_stat, reg_stamp)


def load_policy(*, trust: Callable[[Path], Trust] | None = None) -> PolicyLayers:
    """Resolve every source. `trust` replaces the ownership check (tests)."""
    global _CACHE
    checker = trust or assess_trust
    if trust is None and _CACHE is not None and _CACHE[0] == _stamp():
        return _CACHE[1]

    layers = PolicyLayers()
    registry = read_registry_policy()
    if registry:
        try:
            values, unknown = normalize_document(registry)
            layers.sources.append(PolicySource(
                "managed", r"HKLM\SOFTWARE\Policies\Agentmetry", True,
                "HKLM is not writable by a standard user", tuple(values), unknown,
            ))
            layers.locked.update(values)
        except PolicySyntax as exc:
            layers.sources.append(PolicySource(
                "managed", r"HKLM\SOFTWARE\Policies\Agentmetry", False, str(exc),
            ))

    for path in platform_managed_candidates():
        source, values = _consider_file(path, "managed", checker)
        if source.reason == "absent":
            continue
        layers.sources.append(source)
        if source.accepted:
            for key, value in values.items():
                layers.locked.setdefault(key, value)

    user_source, user_values = _consider_file(user_policy_path(), "user", checker)
    if user_source.reason != "absent":
        layers.sources.append(user_source)
        if user_source.accepted:
            layers.user.update(user_values)

    if trust is None:
        _CACHE = (_stamp(), layers)
    return layers


def _env_text(spec: KeySpec, value: Any) -> str:
    if spec.kind == "bool":
        return "true" if value else "false"
    return str(value)


def _env_is_set(spec: KeySpec) -> bool:
    wanted = spec.env.lower()
    return any(key.lower() == wanted for key in os.environ)


def overlay_settings(settings: Any) -> PolicyLayers:
    """Apply locks to a Settings object, and user-file values where nothing else set them.

    Locks also land in `os.environ`, because `api_token.auth_disabled` and the
    heartbeat read the environment directly. A locked `auth_disabled: false`
    therefore clears a developer `AGENTMETRY_AUTH_DISABLED=1` in this process.
    """
    layers = load_policy()
    for key, spec in SPECS.items():
        if key in layers.locked:
            _assign(settings, spec, layers.locked[key])
            continue
        if key not in layers.user:
            continue
        current = getattr(settings, spec.field, None) if spec.field else None
        if spec.field and current != _DEFAULTS.get(key):
            continue
        if _env_is_set(spec):
            continue
        _assign(settings, spec, layers.user[key])
    return layers


def _assign(settings: Any, spec: KeySpec, value: Any) -> None:
    os.environ[spec.env] = _env_text(spec, value)
    if spec.field and hasattr(settings, spec.field):
        setattr(settings, spec.field, value)
    if spec.field == "" and spec.env == "AGENTMETRY_DATA_DIR":
        root = Path(str(value)).expanduser()
        for field_name, filename in _DATA_FILES.items():
            if hasattr(settings, field_name):
                setattr(settings, field_name, root / filename)


def apply_locked_env() -> PolicyLayers:
    """Put locked keys into this process's environment. The hook calls this once.

    Child IDE hooks do not inherit the daemon's environment. They read the
    managed file themselves, here, so a user `AGENTMETRY_DLP_MODE=disable`
    does not downgrade a locked `block`.
    """
    layers = load_policy()
    for key, value in layers.locked.items():
        spec = SPECS[key]
        os.environ[spec.env] = _env_text(spec, value)
    return layers


def locked_value(key: str) -> Any:
    """The locked value, or None. Used by the hook's settings resolver."""
    return load_policy().locked.get(key)


def user_value(key: str) -> Any:
    return load_policy().user.get(key)
