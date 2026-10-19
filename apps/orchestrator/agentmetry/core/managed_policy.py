"""Fleet locks: a managed policy pins settings a developer cannot change. Standard library only.

A solo install has no managed policy, and nothing here changes a default. A
fleet puts one where only an administrator can write, and every key it sets is
locked: the process environment and `.env` can no longer change it, in the
recorder or in any hook.

Sources, the first to set a key wins:

1. `HKLM\\SOFTWARE\\Policies\\Agentmetry` on Windows. Trusted by location, the way
   Group Policy is: a standard user cannot write under HKLM\\SOFTWARE\\Policies.
   Value names are matched case-insensitively.
2. A policy file at the platform location: `%ProgramData%\\Agentmetry\\policy.yaml`
   (the real ProgramData, from the shell, not the `PROGRAMDATA` variable a user
   can set); `/Library/Managed Preferences/ai.agentmetry.sensor.plist`, where an
   MDM profile lands, and `/etc/agentmetry/policy.yaml` on macOS;
   `/etc/agentmetry/policy.yaml` elsewhere.
3. `AGENTMETRY_POLICY_DIR` (or `--policy-dir`), for an installer that keeps its
   policy beside itself. It adds a location and never replaces one, and its
   files pass the same check, so a developer who points it somewhere gains
   nothing they could not already set in their own environment.

A file is honoured only when the person it constrains cannot change it, and
it is checked on the open handle the policy is then read from, so it cannot be
swapped between the check and the read:

* Windows: owned by SYSTEM, Administrators or TrustedInstaller, with no allow
  ACE giving any other SID write, delete or control of the file, and a parent
  directory with the same owner rule where no other SID can create, delete or
  re-permission entries. Decided from SIDs, so a German `NT-AUTORITÄT\\SYSTEM`
  is the same SYSTEM. A file a user created is owned by that user and refused,
  which is what stops a file being planted in a ProgramData folder that
  inherited `Users: create files`. Neither path may be a reparse point.
* POSIX: owned by root and not group or world writable, the same for every
  directory above it, no symlink at the file, root-owned symlinks only above
  it, and no ACL entry granting another user or group write.

A file that fails the check, or that does not parse, is refused whole. A typo
cannot lock half a policy and quietly drop the key the admin cared about.
`doctor` fails on it, and the heartbeat reports it as `degraded`.

Locks are applied to the environment once, at process start (`apply_locks`),
before `core.config` builds `Settings`, so a lock reaches the hook's
pydantic-free resolver and the orchestrator alike. A changed policy takes
effect when the process restarts. What a lock cannot stop is a developer who
removes the hook from their IDE; hook coverage reports that.
"""

from __future__ import annotations

import os
import re
import stat
import sys
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA = 1
REGISTRY_KEY = r"SOFTWARE\Policies\Agentmetry"
REGISTRY_LOCATION = "HKLM\\" + REGISTRY_KEY

#: False only in the test suite. conftest clears it before anything imports
#: `core.config`, so a policy on the maintainer's machine cannot lock the DLP
#: mode of every test. Deliberately not an environment variable: a variable
#: that turns managed policy off is the bypass this module exists to close.
HOST_SOURCES = True

#: Larger than any policy needs. A managed location is not a place to read a
#: gigabyte from on every tool call.
_MAX_BYTES = 64 * 1024

_PACKAGE = Path(__file__).resolve().parents[1]  # agentmetry/
_BUILT_IN_RULES = {
    "dlp_rules_path": _PACKAGE / "policies" / "dlp" / "manifest.yaml",
    "tool_policy_path": _PACKAGE / "policies" / "tool" / "manifest.yaml",
}
#: A locked mode pins its rules too. Otherwise `dlp_mode: block` is undone by
#: pointing AGENTMETRY_DLP_RULES_PATH at an empty manifest. A fleet with its own
#: manifest locks the path alongside the mode.
PINNED_BY = {"dlp_rules_path": "dlp_mode", "tool_policy_path": "tool_policy_mode"}
#: A locked data_dir pins the files Settings would otherwise let one variable
#: each move out of it. The hook derives its spool from the trail's path, so
#: without this a locked directory is sidestepped by repointing one file.
_DATA_FILES = {
    "AGENTMETRY_AUDIT_EXPORT_PATH": "audit-forward.jsonl",
    "AGENTMETRY_AUDIT_DB_PATH": "audit.db",
    "AGENTMETRY_DETECTION_LIVE_DB_PATH": "detection_live.db",
    "AGENTMETRY_DETECTION_DISPOSITION_DB_PATH": "detection_disposition.db",
}


@dataclass(frozen=True)
class KeySpec:
    env: str
    kind: str  # bool, int, str, path, sink
    choices: frozenset[str] = frozenset()


_MODES = frozenset({"log", "block", "disable"})
#: `parse_sink_modes` vocabulary, restated so the hook does not import sinks.
_SINKS = frozenset({"file", "webhook", "elastic", "splunk", "chronicle", "sentinel", "both", "all"})

#: Operational settings only. Secrets (API keys, SIEM credentials, the hash key)
#: stay in the service environment: a policy file is readable by every user.
SPECS: dict[str, KeySpec] = {
    "dlp_mode": KeySpec("AGENTMETRY_DLP_MODE", "str", _MODES),
    "dlp_pii": KeySpec("AGENTMETRY_DLP_PII", "bool"),
    "dlp_rules_path": KeySpec("AGENTMETRY_DLP_RULES_PATH", "path"),
    "tool_policy_mode": KeySpec("AGENTMETRY_TOOL_POLICY_MODE", "str", _MODES),
    "tool_policy_path": KeySpec("AGENTMETRY_TOOL_POLICY_PATH", "path"),
    "auth_disabled": KeySpec("AGENTMETRY_AUTH_DISABLED", "bool"),
    "trusted_hosts": KeySpec("AGENTMETRY_TRUSTED_HOSTS", "str"),
    "audit_sink": KeySpec("AGENTMETRY_AUDIT_SINK", "sink"),
    "auto_install_hooks": KeySpec("AGENTMETRY_AUTO_INSTALL_HOOKS", "bool"),
    "data_dir": KeySpec("AGENTMETRY_DATA_DIR", "path"),
    "hook_spool_path": KeySpec("AGENTMETRY_HOOK_SPOOL_PATH", "path"),
    "heartbeat_seconds": KeySpec("AGENTMETRY_HEARTBEAT_SECONDS", "int"),
}

#: pydantic's boolean vocabulary, as policy_settings uses.
_TRUE = frozenset({"1", "on", "t", "true", "y", "yes"})
_FALSE = frozenset({"0", "off", "f", "false", "n", "no"})


class PolicySyntax(ValueError):
    """A document that cannot be applied as written. The whole document is refused."""


class Untrusted(Exception):
    """A managed file the person it constrains could change. Refused unread."""


# ----------------------------------------------------------------------
# Result types
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class PolicySource:
    location: str
    accepted: bool
    reason: str
    keys: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()


@dataclass
class ManagedPolicy:
    locked: dict[str, Any] = field(default_factory=dict)
    sources: list[PolicySource] = field(default_factory=list)

    @property
    def rejected(self) -> list[PolicySource]:
        return [s for s in self.sources if not s.accepted]

    @property
    def pinned(self) -> list[str]:
        """Rules paths held at the built-in manifest because their mode is locked."""
        return [k for k, mode in PINNED_BY.items() if mode in self.locked and k not in self.locked]

    def environment(self) -> dict[str, str]:
        """Every variable the locks set, pins included, as text."""
        out = {SPECS[key].env: _env_text(value) for key, value in self.locked.items()}
        for key in self.pinned:
            out[SPECS[key].env] = str(_BUILT_IN_RULES[key])
        if "data_dir" in self.locked:
            root = Path(str(self.locked["data_dir"]))
            out.update({name: str(root / filename) for name, filename in _DATA_FILES.items()})
        return out


# ----------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------

_KEY = re.compile(r"[a-z][a-z0-9_]*\Z")
_INT = re.compile(r"-?\d+\Z")


def _scalar(raw: str, lineno: int) -> Any:
    if raw[:1] in ("'", '"'):
        quote = raw[0]
        end = raw.find(quote, 1)
        if end == -1:
            raise PolicySyntax(f"line {lineno}: unterminated quote")
        rest = raw[end + 1:].strip()
        if rest and not rest.startswith("#"):
            raise PolicySyntax(f"line {lineno}: text after the closing quote")
        return raw[1:end]
    if " #" in raw:
        raw = raw.split(" #", 1)[0].rstrip()
    if not raw:
        raise PolicySyntax(f"line {lineno}: a key with no value opens a nested map")
    if raw[0] in "[{|>&*!%@`":
        raise PolicySyntax(f"line {lineno}: only flat key: value pairs are a policy")
    low = raw.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if _INT.match(raw):
        return int(raw)
    return raw


def parse_policy_yaml(text: str) -> dict[str, Any]:
    """The flat `key: value` subset of YAML a policy file may be.

    Nesting, lists, anchors and block scalars are refused rather than guessed
    at. A policy that needs them is a program, and PyYAML stays off this path
    so the hook does not pay for it to read a handful of scalars.
    """
    data: dict[str, Any] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#") or line == "---":
            continue
        if raw[:1].isspace():
            raise PolicySyntax(f"line {lineno}: indented, so nested; a policy is flat")
        if line.startswith("- "):
            raise PolicySyntax(f"line {lineno}: lists are not a policy")
        key, sep, value = line.partition(":")
        key = key.strip()
        if not sep or not _KEY.match(key):
            raise PolicySyntax(f"line {lineno}: expected `key: value` with a lower-case key")
        if key in data:
            raise PolicySyntax(f"line {lineno}: {key} is set twice")
        data[key] = _scalar(value.strip(), lineno)
    return data


def parse_policy_plist(blob: bytes) -> dict[str, Any]:
    import plistlib  # Lazy: only a Mac with an MDM profile pays for it.

    try:
        loaded = plistlib.loads(blob)
    except Exception as exc:  # plistlib raises several types for one meaning
        raise PolicySyntax(f"not a property list: {exc}") from exc
    if not isinstance(loaded, dict):
        raise PolicySyntax("plist root must be a dictionary")
    return loaded


def _coerce(key: str, value: Any) -> Any:
    spec = SPECS[key]
    if spec.kind == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and value in (0, 1):  # REG_DWORD
            return bool(value)
        text = str(value).strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        raise PolicySyntax(f"{key}: {value!r} is not a boolean")
    if spec.kind == "int":
        if isinstance(value, bool):
            raise PolicySyntax(f"{key}: {value!r} is not a whole number")
        try:
            number = int(str(value).strip())
        except ValueError as exc:
            raise PolicySyntax(f"{key}: {value!r} is not a whole number") from exc
        if number < 0:
            raise PolicySyntax(f"{key}: must not be negative")
        return number
    if not isinstance(value, str):
        raise PolicySyntax(f"{key}: {value!r} is not text")
    text = value.strip()
    if spec.choices and text not in spec.choices:
        raise PolicySyntax(f"{key}: {text!r} is not one of {', '.join(sorted(spec.choices))}")
    if spec.kind == "sink":
        parts = [p.strip().lower() for p in text.split(",") if p.strip()]
        bad = [p for p in parts if p not in _SINKS]
        if not parts or bad:
            raise PolicySyntax(f"audit_sink: {text!r} is not a list of {', '.join(sorted(_SINKS))}")
        return ",".join(parts)
    if spec.kind == "path":
        # Relative would resolve against each process's working directory, so
        # the hook and the recorder would lock two different files.
        if not text or not Path(text).is_absolute():
            raise PolicySyntax(f"{key}: {text!r} is not an absolute path")
    return text


def normalize_document(data: dict[str, Any]) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Known keys coerced and checked; unknown key names, which are reported, not applied.

    One bad value refuses the document. An unknown key does not, so a policy
    written for a newer release still locks what this one understands, and
    `doctor` names what it ignored.
    """
    schema = data.get("schema", SCHEMA)
    if isinstance(schema, bool) or str(schema).strip() != str(SCHEMA):
        raise PolicySyntax(f"schema {schema!r} is not supported (this release reads {SCHEMA})")
    values: dict[str, Any] = {}
    unknown: list[str] = []
    for key, raw in data.items():
        if key == "schema":
            continue
        if key not in SPECS:
            unknown.append(str(key))
            continue
        values[key] = _coerce(key, raw)
    return values, tuple(sorted(unknown))


def parse_document(path: Path, blob: bytes) -> dict[str, Any]:
    if path.suffix.lower() == ".plist":
        return parse_policy_plist(blob)
    try:
        return parse_policy_yaml(blob.decode("utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise PolicySyntax("not UTF-8 text") from exc


# ----------------------------------------------------------------------
# Trust: POSIX
# ----------------------------------------------------------------------


def judge_posix(path: str, uid: int, mode: int) -> None:
    """Raise Untrusted unless root owns it and nobody else can write it."""
    if uid != 0:
        raise Untrusted(f"{path} is owned by uid {uid}, not root")
    if mode & 0o022:
        raise Untrusted(f"{path} is writable by its group or by everyone")


def _check_posix_dirs(directory: Path) -> None:
    """Every directory from / down: root-owned and not writable by others.

    A symlink is allowed above the file only when root owns it (macOS `/etc`
    is one), and the directories it leads to are then checked as well.
    """
    anchor = Path(directory.anchor)
    parts = directory.parts
    chain = [anchor, *(anchor.joinpath(*parts[1:i]) for i in range(2, len(parts) + 1))]
    for entry in chain:
        try:
            st = os.lstat(entry)
        except OSError as exc:
            raise Untrusted(f"cannot inspect {entry}: {exc.strerror or exc}") from exc
        if stat.S_ISLNK(st.st_mode):
            if st.st_uid != 0:
                raise Untrusted(f"{entry} is a symlink owned by uid {st.st_uid}, not root")
            continue
        if not stat.S_ISDIR(st.st_mode):
            raise Untrusted(f"{entry} is not a directory")
        judge_posix(str(entry), st.st_uid, stat.S_IMODE(st.st_mode))
    real = Path(os.path.realpath(directory))
    if real != directory:
        _check_posix_dirs(real)


_ACL_USER, _ACL_GROUP = 0x02, 0x08


def linux_acl_grants_write(blob: bytes) -> bool:
    """Whether a `system.posix_acl_access` value names a non-root user or group with write.

    Format: a 4-byte version, then 8-byte entries of tag (u16), perm (u16) and
    id (u32), little-endian. The owner, group and other entries are the mode
    bits, already checked.
    """
    for offset in range(4, len(blob) - 7, 8):
        tag = int.from_bytes(blob[offset:offset + 2], "little")
        perm = int.from_bytes(blob[offset + 2:offset + 4], "little")
        ident = int.from_bytes(blob[offset + 4:offset + 8], "little")
        if tag in (_ACL_USER, _ACL_GROUP) and perm & 0o2 and ident != 0:
            return True
    return False


_MAC_WRITE = frozenset({
    "write", "append", "writeattr", "writeextattr", "writesecurity", "chown",
    "delete", "add_file", "add_subdirectory", "delete_child",
})


def mac_acl_grants_write(text: str) -> bool:
    """Whether `acl_to_text` output allows a non-root principal to change the object.

    Each entry is `tag:uuid:name:id:allow|deny:perm,perm`. Deny entries only
    take access away, so only allow entries are read.
    """
    for line in text.splitlines():
        parts = line.strip().split(":")
        if len(parts) < 6 or parts[0] not in ("user", "group"):
            continue
        ident, kind, perms = parts[3], parts[-2], set(parts[-1].split(","))
        if kind == "allow" and perms & _MAC_WRITE and ident != "0":
            return True
    return False


def _check_posix_acl(target: int | Path, label: str) -> None:
    if sys.platform.startswith("linux"):
        import errno

        try:
            blob = os.getxattr(target, "system.posix_acl_access")
        except OSError as exc:
            if exc.errno in (errno.ENODATA, errno.ENOTSUP, errno.EOPNOTSUPP):
                return
            raise Untrusted(f"cannot read the ACL of {label}: {exc.strerror or exc}") from exc
        if linux_acl_grants_write(blob):
            raise Untrusted(f"an ACL on {label} lets another user or group write it")
        return
    if sys.platform == "darwin":
        try:
            text = _mac_acl_text(target)
        except Untrusted:
            raise
        except Exception as exc:
            raise Untrusted(f"cannot read the ACL of {label}: {exc}") from exc
        if text and mac_acl_grants_write(text):
            raise Untrusted(f"an ACL on {label} lets another user or group change it")


def _mac_acl_text(target: int | Path) -> str:
    import ctypes
    import ctypes.util

    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    extended = 0x00000100  # ACL_TYPE_EXTENDED
    if isinstance(target, int):
        get = libc.acl_get_fd_np
        get.argtypes = [ctypes.c_int, ctypes.c_int]
    else:
        get = libc.acl_get_link_np
        get.argtypes = [ctypes.c_char_p, ctypes.c_int]
        target = os.fsencode(target)
    get.restype = ctypes.c_void_p
    libc.acl_to_text.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    libc.acl_to_text.restype = ctypes.c_void_p
    libc.acl_free.argtypes = [ctypes.c_void_p]
    acl = get(target, extended)
    if not acl:
        return ""  # ENOENT: no extended ACL
    try:
        text_ptr = libc.acl_to_text(acl, None)
        if not text_ptr:
            raise Untrusted("cannot render an ACL to check it")
        try:
            return ctypes.string_at(text_ptr).decode("utf-8", "replace")
        finally:
            libc.acl_free(text_ptr)
    finally:
        libc.acl_free(acl)


def _read_posix(path: Path) -> bytes:
    _check_posix_dirs(path.parent)
    # The real folder's ACL, not a symlink's: macOS reaches /etc through one.
    folder = Path(os.path.realpath(path.parent))
    _check_posix_acl(folder, str(folder))
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags | getattr(os, "O_CLOEXEC", 0))
    except OSError as exc:
        raise Untrusted(f"cannot open {path} without following a link: {exc.strerror or exc}") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise Untrusted(f"{path} is not a regular file")
        judge_posix(str(path), st.st_uid, stat.S_IMODE(st.st_mode))
        _check_posix_acl(fd, str(path))
        blob = os.read(fd, _MAX_BYTES + 1)
    finally:
        os.close(fd)
    if len(blob) > _MAX_BYTES:
        raise Untrusted(f"{path} is larger than {_MAX_BYTES} bytes")
    return blob


# ----------------------------------------------------------------------
# Trust: Windows
# ----------------------------------------------------------------------

SYSTEM_SID = "S-1-5-18"
ADMINISTRATORS_SID = "S-1-5-32-544"
TRUSTED_INSTALLER_SID = "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"
PRIVILEGED_SIDS = frozenset({SYSTEM_SID, ADMINISTRATORS_SID, TRUSTED_INSTALLER_SID})

_DELETE, _WRITE_DAC, _WRITE_OWNER = 0x00010000, 0x00040000, 0x00080000
_GENERIC_ALL, _GENERIC_WRITE = 0x10000000, 0x40000000
_CONTROL = _DELETE | _WRITE_DAC | _WRITE_OWNER | _GENERIC_ALL | _GENERIC_WRITE
#: FILE_WRITE_DATA, FILE_APPEND_DATA. On a directory the same bits are
#: FILE_ADD_FILE and FILE_ADD_SUBDIRECTORY; 0x40 is FILE_DELETE_CHILD.
FILE_WRITE_MASK = 0x0002 | 0x0004 | _CONTROL
DIR_WRITE_MASK = 0x0002 | 0x0004 | 0x0040 | _CONTROL

_ALLOWED_TYPES = frozenset({0x0, 0x9})  # ACCESS_ALLOWED, ACCESS_ALLOWED_CALLBACK
_DENIED_TYPES = frozenset({0x1, 0xA})
_INHERIT_ONLY = 0x08


@dataclass(frozen=True)
class Ace:
    ace_type: int
    flags: int
    mask: int
    sid: str


def judge_windows(label: str, owner: str, aces: list[Ace] | None, write_mask: int) -> None:
    """Raise Untrusted unless only privileged SIDs own or can change the object.

    `aces is None` is a NULL DACL, which grants everyone everything. Deny ACEs
    only take access away and are ignored, which can refuse a file a careful
    admin locked down with denies, never accept one that is open. Inherit-only
    ACEs apply to children created later, not to this object.
    """
    if owner not in PRIVILEGED_SIDS:
        raise Untrusted(f"{label} is owned by {owner}, not SYSTEM, Administrators or TrustedInstaller")
    if aces is None:
        raise Untrusted(f"{label} has no DACL, so everyone can change it")
    for ace in aces:
        if ace.ace_type in _DENIED_TYPES or ace.flags & _INHERIT_ONLY:
            continue
        if ace.ace_type not in _ALLOWED_TYPES:
            raise Untrusted(f"{label} has an ACE of type {ace.ace_type:#x} this check does not read")
        if ace.sid not in PRIVILEGED_SIDS and ace.mask & write_mask:
            raise Untrusted(f"{ace.sid} can modify {label} (access mask {ace.mask:#x})")


def _windows_security(*, handle: int | None = None, path: Path | None = None) -> tuple[str, list[Ace] | None]:
    """Owner SID and DACL of an open handle or a path, through advapi32."""
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    pp = ctypes.POINTER(ctypes.c_void_p)
    owner, dacl, sd = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    what = 0x1 | 0x4  # OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION
    if handle is not None:
        fn = advapi32.GetSecurityInfo
        fn.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.DWORD, pp, pp, pp, pp, pp]
        target: Any = wintypes.HANDLE(handle)
    else:
        fn = advapi32.GetNamedSecurityInfoW
        fn.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD, pp, pp, pp, pp, pp]
        target = str(path)
    fn.restype = wintypes.DWORD
    rc = fn(target, 1, what, ctypes.byref(owner), None, ctypes.byref(dacl), None, ctypes.byref(sd))
    if rc != 0:
        raise Untrusted(f"cannot read the security descriptor (Windows error {rc})")

    def sid_text(ptr: int) -> str:
        out = wintypes.LPWSTR()
        convert = advapi32.ConvertSidToStringSidW
        convert.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
        if not convert(ptr, ctypes.byref(out)):
            raise Untrusted(f"cannot read a SID (Windows error {ctypes.get_last_error()})")
        try:
            return out.value or ""
        finally:
            kernel32.LocalFree(ctypes.cast(out, ctypes.c_void_p))

    try:
        owner_sid = sid_text(owner.value) if owner.value else ""
        if not dacl.value:
            return owner_sid, None

        class AclSizeInformation(ctypes.Structure):
            _fields_ = [("AceCount", wintypes.DWORD), ("AclBytesInUse", wintypes.DWORD),
                        ("AclBytesFree", wintypes.DWORD)]

        info = AclSizeInformation()
        advapi32.GetAclInformation.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_int]
        if not advapi32.GetAclInformation(dacl, ctypes.byref(info), ctypes.sizeof(info), 2):
            raise Untrusted(f"cannot read the DACL (Windows error {ctypes.get_last_error()})")
        advapi32.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, pp]
        aces: list[Ace] = []
        for index in range(info.AceCount):
            ace = ctypes.c_void_p()
            if not advapi32.GetAce(dacl, index, ctypes.byref(ace)):
                raise Untrusted(f"cannot read ACE {index} (Windows error {ctypes.get_last_error()})")
            base = ace.value or 0
            ace_type = ctypes.c_ubyte.from_address(base).value
            flags = ctypes.c_ubyte.from_address(base + 1).value
            mask = ctypes.c_uint32.from_address(base + 4).value
            # Header (4 bytes) and mask (4) precede the SID for the allow and
            # deny types; other layouts are recorded unread and refused.
            readable = ace_type in _ALLOWED_TYPES | _DENIED_TYPES
            aces.append(Ace(ace_type, flags, mask, sid_text(base + 8) if readable else ""))
        return owner_sid, aces
    finally:
        kernel32.LocalFree(sd)


def _not_a_reparse_point(path: Path) -> None:
    try:
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    except OSError as exc:
        raise Untrusted(f"cannot inspect {path}: {exc.strerror or exc}") from exc
    if attributes & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
        raise Untrusted(f"{path} is a link or junction, not a managed policy")


def _read_windows(path: Path) -> bytes:
    import msvcrt

    for entry in (path.parent, path):
        _not_a_reparse_point(entry)
    owner, aces = _windows_security(path=path.parent)
    judge_windows(str(path.parent), owner, aces, DIR_WRITE_MASK)
    with open(path, "rb") as fh:
        opened, named = os.fstat(fh.fileno()), os.lstat(path)
        if (opened.st_ino, opened.st_dev) != (named.st_ino, named.st_dev):
            raise Untrusted(f"{path} changed while it was being checked")
        owner, aces = _windows_security(handle=msvcrt.get_osfhandle(fh.fileno()))
        judge_windows(str(path), owner, aces, FILE_WRITE_MASK)
        blob = fh.read(_MAX_BYTES + 1)
    if len(blob) > _MAX_BYTES:
        raise Untrusted(f"{path} is larger than {_MAX_BYTES} bytes")
    return blob


def read_trusted(path: Path) -> bytes:
    """The file's bytes, if only an administrator could have written them."""
    if not path.is_absolute():
        raise Untrusted(f"{path} is not an absolute path")
    if os.name == "nt":
        return _read_windows(path)
    return _read_posix(path)


def remediation(location: str) -> str:
    """One line on how to make a refused file acceptable, for doctor."""
    if os.name == "nt":
        folder = str(Path(location).parent)
        # Owner first: once the ACL is locked down, the account running this
        # may no longer hold the right to take ownership.
        return (
            f'From an elevated prompt: icacls "{folder}" /setowner *{ADMINISTRATORS_SID} /T, '
            f'then icacls "{folder}" /inheritance:r /grant:r *{SYSTEM_SID}:(OI)(CI)F '
            f'*{ADMINISTRATORS_SID}:(OI)(CI)F *S-1-5-32-545:(OI)(CI)RX /T.'
        )
    return "Make it and every directory above it root-owned and not group or world writable."


# ----------------------------------------------------------------------
# Sources
# ----------------------------------------------------------------------


def _program_data() -> Path:
    """The real ProgramData. `%PROGRAMDATA%` is the user's to change, so it is not asked."""
    import ctypes
    from ctypes import wintypes

    class Guid(ctypes.Structure):
        _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD),
                    ("d", ctypes.c_ubyte * 8)]

    # FOLDERID_ProgramData {62AB5D82-FDC1-4DC3-A9DD-070D1D495D97}
    folder = Guid(0x62AB5D82, 0xFDC1, 0x4DC3, (ctypes.c_ubyte * 8)(0xA9, 0xDD, 0x07, 0x0D, 0x1D, 0x49, 0x5D, 0x97))
    shell32 = ctypes.WinDLL("shell32")
    ole32 = ctypes.WinDLL("ole32")
    out = ctypes.c_wchar_p()
    shell32.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(Guid), wintypes.DWORD, wintypes.HANDLE,
                                             ctypes.POINTER(ctypes.c_wchar_p)]
    shell32.SHGetKnownFolderPath.restype = ctypes.c_long
    if shell32.SHGetKnownFolderPath(ctypes.byref(folder), 0, None, ctypes.byref(out)) != 0:
        return Path(r"C:\ProgramData")
    try:
        return Path(out.value or r"C:\ProgramData")
    finally:
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        ole32.CoTaskMemFree(ctypes.cast(out, ctypes.c_void_p))


def managed_locations() -> list[Path]:
    """Policy files to consider, highest first. Missing ones are skipped by the loader."""
    if os.name == "nt":
        try:
            program_data = _program_data()
        except OSError:
            program_data = Path(r"C:\ProgramData")
        found = [program_data / "Agentmetry" / "policy.yaml"]
    elif sys.platform == "darwin":
        found = [Path("/Library/Managed Preferences/ai.agentmetry.sensor.plist"),
                 Path("/etc/agentmetry/policy.yaml")]
    else:
        found = [Path("/etc/agentmetry/policy.yaml")]
    extra = os.environ.get("AGENTMETRY_POLICY_DIR", "").strip()
    if extra:
        root = Path(extra).expanduser()
        if root.suffix.lower() in (".yaml", ".yml", ".plist"):
            found.append(root)
        else:
            found += [root / "policy.yaml", root / "policy.plist"]
    return found


def read_registry_policy() -> dict[str, Any] | None:
    """HKLM policy values with lower-cased names, or None where there is no key."""
    if os.name != "nt":
        return None
    import winreg

    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REGISTRY_KEY, 0,
                             winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0))
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
            if name:  # the unnamed default value is not a policy key
                values[str(name).lower()] = raw
            index += 1
    finally:
        winreg.CloseKey(key)
    return values


def _read_file_source(path: Path, reader: Callable[[Path], bytes]) -> tuple[PolicySource, dict[str, Any]] | None:
    try:
        if not path.is_file():
            return None
    except OSError:
        return None
    try:
        blob = reader(path)
    except Untrusted as exc:
        return PolicySource(str(path), False, f"not trusted: {exc}"), {}
    except OSError as exc:
        return PolicySource(str(path), False, f"cannot read: {exc.strerror or exc}"), {}
    except Exception as exc:
        # A check that could not run is a check that did not pass.
        return PolicySource(str(path), False, f"could not be checked: {exc}"), {}
    try:
        values, unknown = normalize_document(parse_document(path, blob))
    except PolicySyntax as exc:
        return PolicySource(str(path), False, f"refused: {exc}"), {}
    return PolicySource(str(path), True, "trusted", tuple(values), unknown), values


def load_policy(
    *,
    locations: list[Path] | None = None,
    registry: dict[str, Any] | None = None,
    reader: Callable[[Path], bytes] | None = None,
) -> ManagedPolicy:
    """Every managed source, resolved. Never raises for a bad source; it is recorded.

    With no arguments the host's sources are read (unless `HOST_SOURCES` is
    off). Tests pass `locations`, `registry` and `reader` instead.
    """
    if locations is None:
        locations = managed_locations() if HOST_SOURCES else []
    if registry is None and HOST_SOURCES:
        registry = read_registry_policy()
    reader = reader or read_trusted

    policy = ManagedPolicy()
    if registry:
        try:
            values, unknown = normalize_document(registry)
        except PolicySyntax as exc:
            policy.sources.append(PolicySource(REGISTRY_LOCATION, False, f"refused: {exc}"))
        else:
            policy.sources.append(PolicySource(REGISTRY_LOCATION, True, "HKLM policy key",
                                               tuple(values), unknown))
            policy.locked.update(values)
    for path in locations:
        found = _read_file_source(path, reader)
        if found is None:
            continue
        source, values = found
        policy.sources.append(source)
        for key, value in values.items():
            policy.locked.setdefault(key, value)
    return policy


def _env_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def apply_locks(
    environ: MutableMapping[str, str] | None = None,
    policy: ManagedPolicy | None = None,
) -> ManagedPolicy:
    """Write every locked value into the environment, over whatever was there.

    Variants of the same name in another case are removed first. Both
    resolvers match case-insensitively, and on POSIX a developer's
    `agentmetry_dlp_mode=disable` beside our `AGENTMETRY_DLP_MODE=block` would
    otherwise be decided by dictionary order.
    """
    env = os.environ if environ is None else environ
    policy = load_policy() if policy is None else policy
    for name, value in policy.environment().items():
        for existing in [k for k in env if k.upper() == name and k != name]:
            del env[existing]
        env[name] = value
    return policy
