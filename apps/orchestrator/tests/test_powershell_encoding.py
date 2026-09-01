"""Windows PowerShell 5.1 must be able to parse the installers.

PowerShell 5.1 is the version that ships with Windows and is what the documented
install command runs. It reads a file with no byte order mark using the system
ANSI code page, not UTF-8. So a single non-ASCII character in a BOM-less script
arrives as mojibake, and if it lands inside a string literal the file fails to
*parse*, which means the installer body never begins executing.

That happened. `scripts/install.ps1` contained an em dash, and the documented
command failed on a fresh clone with "The string is missing the terminator"
pointing at a line that was perfectly well formed in UTF-8 (issue #133). Seven
of the eleven scripts carried the same character, and `install_qoder_hooks.ps1`
legitimately contains CJK in a product name, so removing em dashes alone would
not have been enough.

Two independent guarantees, because either alone can be undone by accident:

* every `.ps1` file starts with a UTF-8 BOM, so PowerShell 5.1 decodes it
  correctly whatever it contains
* no `.ps1` file contains an em dash, which is a house rule for public copy
  anyway and is the specific character that broke it

The parse itself is checked by CI on Windows, not here, because a Linux runner
has no PowerShell 5.1 to parse with.
"""

from __future__ import annotations

from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
BOM = b"\xef\xbb\xbf"


def _scripts() -> list[Path]:
    if not SCRIPTS.is_dir():
        pytest.skip(f"scripts directory not found at {SCRIPTS}")
    found = sorted(SCRIPTS.glob("*.ps1"))
    if not found:
        pytest.skip("no PowerShell scripts to check")
    return found


def test_every_powershell_script_has_a_utf8_bom():
    """Without it, PowerShell 5.1 decodes as ANSI and non-ASCII becomes mojibake."""
    missing = [p.name for p in _scripts() if not p.read_bytes().startswith(BOM)]
    assert not missing, (
        f"no UTF-8 BOM: {missing}. Windows PowerShell 5.1 will read these as "
        "the system ANSI code page, and any non-ASCII character will break the "
        "parse before the script runs."
    )


def test_no_em_dash_in_powershell_scripts():
    """The exact character that broke the documented install command."""
    offenders = []
    for path in _scripts():
        text = path.read_bytes().decode("utf-8")
        for number, line in enumerate(text.splitlines(), 1):
            if "—" in line:
                offenders.append(f"{path.name}:{number}")
    assert not offenders, (
        f"em dash in: {offenders}. Use a comma, a colon or a full stop. This is "
        "the house rule for public copy, and it is also what made install.ps1 "
        "unparseable on the default Windows shell."
    )


def test_hook_installers_prefer_the_orchestrator_venv():
    """Global python has no `agentmetry` on a clean machine.

    `install.ps1` builds the venv and installs into it, so a hook installer that
    resolves bare `python` fails with ModuleNotFoundError on exactly the machine
    a first-time user is running it from.
    """
    offenders = []
    for path in sorted(SCRIPTS.glob("install_*_hooks.ps1")):
        text = path.read_bytes().decode("utf-8")
        if "Get-Command python" in text and ".venv\\Scripts\\python.exe" not in text:
            offenders.append(path.name)
    assert not offenders, (
        f"resolves global python with no venv fallback: {offenders}"
    )


def test_top_level_installer_checks_hook_exit_codes():
    """A native command's exit code does not trip $ErrorActionPreference.

    Each hook installer checks its own `$LASTEXITCODE`. That is worth nothing if
    the caller ignores it, which is how `install.ps1` printed "Install complete"
    and exited 0 after both hook installers had failed.
    """
    text = (SCRIPTS / "install.ps1").read_bytes().decode("utf-8")
    hook_block = text.split("Installing IDE hooks", 1)
    assert len(hook_block) == 2, "hook install step not found in install.ps1"
    after = hook_block[1].split("Write-Step", 1)[0]
    assert "$LASTEXITCODE" in after, (
        "install.ps1 runs the hook installers without checking their exit code, "
        "so a failed hook install still reports success."
    )
