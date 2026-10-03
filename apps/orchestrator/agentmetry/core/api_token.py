"""The per-install API token (pilot hardening item 8). Standard library only.

The API used to run with no authentication unless somebody set
AGENTMETRY_API_KEY, and `doctor` reported that as "[OK] loopback only (no API
key needed)". Loopback is not a boundary: every process on the machine, and any
web page that gets a request through, could read the whole trail, export the
evidence pack, inject events and close detections.

Now the first boot writes a random token to `<data dir>/api-token`, and every
route requires it. The hook, the CLI and the OTel receiver read the same file,
so nothing has to be configured. AGENTMETRY_API_KEY still wins when it is set
(a fleet that distributes its own key), and AGENTMETRY_AUTH_DISABLED=1 is the
explicit development override.

The file is created owner-only: mode 0600 on POSIX, and on Windows the
inherited ACL is replaced with one entry for the current user. A machine-wide
service install (the MSI) sets AGENTMETRY_TOKEN_SHARED=1 so that developers'
hooks, which run as each user, can read a token the service created; the MSI is
then responsible for that file's ACL.

Standard library only: the hook reads this on every tool call.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from agentmetry.core.paths import data_dir

TOKEN_FILE = "api-token"  # noqa: S105 (a file name, not a secret)
INGEST_TOKEN_FILE = "ingest-token"  # noqa: S105 (a file name, not a secret)
#: BUILTIN\Users, by SID so it resolves on any display language.
_USERS_SID = "*S-1-5-32-545"
_TRUTHY = ("1", "true", "yes", "on")


def token_path() -> Path:
    explicit = os.environ.get("AGENTMETRY_API_TOKEN_FILE", "").strip()
    return Path(explicit) if explicit else data_dir() / TOKEN_FILE


def ingest_token_path() -> Path:
    """An ingest-only credential for hooks, when an extension provisions one.

    The core does not mint it. Agentmetry Enterprise writes a host-bound,
    ingest-scoped token here on a machine-wide install, so a developer's hook
    can send events without being able to read the trail or close detections.
    """
    explicit = os.environ.get("AGENTMETRY_INGEST_TOKEN_FILE", "").strip()
    return Path(explicit) if explicit else data_dir() / INGEST_TOKEN_FILE


def read_token(path: Path | None = None) -> str:
    """The token on disk, or empty. Never creates one."""
    try:
        return (path or token_path()).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _restrict(path: Path) -> None:
    """Owner-only, best effort. A failure here is reported by `doctor`."""
    import subprocess  # ACL work only; the hook reads tokens on every call
    if os.environ.get("AGENTMETRY_TOKEN_SHARED", "").strip().lower() in _TRUTHY:
        return
    if os.name != "nt":
        os.chmod(path, 0o600)
        return
    user = os.environ.get("USERNAME", "").strip()
    if not user:
        return
    domain = os.environ.get("USERDOMAIN", "").strip()
    principal = f"{domain}\\{user}" if domain else user
    subprocess.run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", f"{principal}:F"],
        capture_output=True, check=False, timeout=15,
    )


_BROAD_PRINCIPALS = ("everyone", "builtin\\users", "authenticated users")


def is_private(path: Path) -> bool | None:
    """Owner-only? None when it cannot be told (or the install shares it on purpose)."""
    import subprocess  # ACL work only; the hook reads tokens on every call
    if os.environ.get("AGENTMETRY_TOKEN_SHARED", "").strip().lower() in _TRUTHY:
        return None
    try:
        if os.name != "nt":
            return (path.stat().st_mode & 0o077) == 0
        out = subprocess.run(
            ["icacls", str(path)], capture_output=True, text=True, check=False, timeout=15
        ).stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return None
    if not out:
        return None
    return not any(p in out for p in _BROAD_PRINCIPALS)


def ensure_token(path: Path | None = None) -> str:
    """The token, creating it once if it does not exist yet."""
    import subprocess  # ACL work only; the hook reads tokens on every call
    target = path or token_path()
    existing = read_token(target)
    if existing:
        return existing
    target.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    try:
        # O_EXCL: two processes booting at once must not each write their own.
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return read_token(target)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(token)
    try:
        _restrict(target)
    except (OSError, subprocess.SubprocessError):
        pass
    return token


def write_ingest_token(token: str, path: Path | None = None) -> Path:
    """Write the ingest-only token where hooks look for it.

    On a shared (machine-wide) install every local user's hook must read it,
    so it is granted read to the local Users group; it can only send events.
    Otherwise it is owner-only like the full token. Replaced atomically, so a
    hook never reads half a token.
    """
    import subprocess  # ACL work only; the hook reads tokens on every call
    target = path or ingest_token_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(token, encoding="utf-8")
    os.replace(tmp, target)
    try:
        if os.environ.get("AGENTMETRY_TOKEN_SHARED", "").strip().lower() not in _TRUTHY:
            _restrict(target)
        elif os.name == "nt":
            subprocess.run(
                ["icacls", str(target), "/grant", f"{_USERS_SID}:R"],
                capture_output=True, check=False, timeout=15,
            )
        else:
            os.chmod(target, 0o644)
    except (OSError, subprocess.SubprocessError):
        pass
    return target


def auth_disabled() -> bool:
    return os.environ.get("AGENTMETRY_AUTH_DISABLED", "").strip().lower() in _TRUTHY


def client_token() -> str:
    """What a local client (hook, CLI) presents: the configured key, else the file."""
    return os.environ.get("AGENTMETRY_API_KEY", "").strip() or read_token()
