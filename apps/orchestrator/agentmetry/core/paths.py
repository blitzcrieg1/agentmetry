"""Where Agentmetry keeps its data and its `.env`. Standard library only.

Pilot hardening item 10. Every default path used to be computed relative to
the package's own location: `<package>/../data/audit-forward.jsonl`. In a git
checkout that is `apps/orchestrator/data`, which is right. In a `pip install`
it is `site-packages/data`, and the `.env` was looked up in `site-packages/.env`:
the trail lived beside the interpreter's libraries, shared by every user of
that interpreter, and was deleted by `pip uninstall` or a venv rebuild.

The rule now, most specific first:

1. `AGENTMETRY_DATA_DIR`, when set.
2. `AGENTMETRY_INSTALL_ROOT\\data`, which the MSI sets machine-wide.
3. A git checkout keeps `apps/orchestrator/data`, so development and existing
   installs from a clone do not move.
4. Otherwise the platform's per-user data directory, the same locations
   `platformdirs` uses: `%LOCALAPPDATA%\\Agentmetry` on Windows,
   `~/Library/Application Support/Agentmetry` on macOS, and
   `$XDG_DATA_HOME/agentmetry` (default `~/.local/share/agentmetry`) elsewhere.
   Implemented here rather than imported because the hook resolves this on
   every tool call and must not pay for a third-party import.

Individual `AGENTMETRY_AUDIT_*_PATH` settings still override their own file.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
#: `apps/orchestrator` in a checkout; `site-packages` in an installed wheel.
PACKAGE_PARENT = _HERE.parents[2]


def is_checkout() -> bool:
    """Running from a source checkout (including an editable install)."""
    return (PACKAGE_PARENT / "pyproject.toml").is_file() and (PACKAGE_PARENT / "agentmetry").is_dir()


def user_data_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA", "").strip()
        root = Path(base) if base else Path.home() / "AppData" / "Local"
        return root / "Agentmetry"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Agentmetry"
    base = os.environ.get("XDG_DATA_HOME", "").strip()
    return (Path(base) if base else Path.home() / ".local" / "share") / "agentmetry"


def data_dir() -> Path:
    """The directory the trail, indexes, spool, logs and API token live in."""
    explicit = os.environ.get("AGENTMETRY_DATA_DIR", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    install = os.environ.get("AGENTMETRY_INSTALL_ROOT", "").strip()
    if install:
        return Path(install).expanduser() / "data"
    if is_checkout():
        return PACKAGE_PARENT / "data"
    return user_data_dir()


def env_file() -> Path:
    """The `.env` the orchestrator and the hook read.

    The checkout keeps `apps/orchestrator/.env`. An install reads `.env` from
    its data directory, never from `site-packages`.
    """
    if is_checkout() and not os.environ.get("AGENTMETRY_DATA_DIR", "").strip():
        return PACKAGE_PARENT / ".env"
    return data_dir() / ".env"


def legacy_site_packages_data() -> Path | None:
    """Where an installed wheel before this change kept its data, if it exists.

    Reported by `doctor` rather than moved: a hash-chained trail is evidence,
    and relocating evidence silently is not a recorder's call to make.
    """
    if is_checkout():
        return None
    legacy = PACKAGE_PARENT / "data"
    return legacy if (legacy / "audit-forward.jsonl").exists() else None
