"""Every module path a launcher names must actually be importable.

The one-top-level-package refactor renamed `api`, `cli` and `core` to live under
`agentmetry`. The code and its imports were updated. Nothing else was, because
nothing else is code:

- the Windows scheduled task kept launching `-m cli serve` and exited 1 every
  sixty seconds for a day while `doctor` reported OK,
- `.claude/launch.json` kept `-m uvicorn api.main:app`,
- five scripts under `scripts/` kept `uvicorn api.main:app`.

Three separate discoveries of one rename, each found by a human tripping over
it. A module path inside a string is invisible to every tool that would
otherwise catch this: the type checker, the linter, and the import system all
stop at the quote mark.

So this walks the launchers, extracts the module each one names, and asks the
import system whether it exists. It is deliberately a text scan rather than a
list of known-good strings, because a hardcoded list is exactly the thing that
goes stale during a rename.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ORCHESTRATOR = Path(__file__).resolve().parents[1]

#: `uvicorn some.module:app` and `python -m some.module`, in any launcher.
_UVICORN_TARGET = re.compile(r"uvicorn\s+([A-Za-z_][\w.]*):(\w+)")
_MODULE_FLAG = re.compile(r"-m[\s,\"']+([A-Za-z_][\w.]*)")

#: Stdlib and third-party module names that legitimately appear after `-m`.
_NOT_OURS = frozenset(
    {
        "pip", "venv", "build", "twine", "pytest", "ruff", "uvicorn",
        "http.server", "json.tool", "compileall", "site", "ensurepip",
        "npm", "node",
    }
)


def _launcher_files() -> list[Path]:
    found: list[Path] = []
    scripts = _REPO_ROOT / "scripts"
    if scripts.is_dir():
        for pattern in ("*.bat", "*.cmd", "*.ps1", "*.py", "*.sh"):
            found.extend(scripts.glob(pattern))
    launch_json = _REPO_ROOT / ".claude" / "launch.json"
    if launch_json.is_file():
        found.append(launch_json)
    return sorted(found)


def _targets(text: str) -> set[str]:
    modules = {m.group(1) for m in _UVICORN_TARGET.finditer(text)}
    modules |= {m.group(1) for m in _MODULE_FLAG.finditer(text)}
    # Only judge modules that look like ours. A launcher naming `pip` or a
    # module from another project is not this test's business.
    return {
        m
        for m in modules
        if m not in _NOT_OURS and (m.startswith("agentmetry") or m.split(".")[0] in {"api", "cli", "core"})
    }


@pytest.mark.parametrize("path", _launcher_files(), ids=lambda p: p.name)
def test_launcher_names_an_importable_module(path: Path, monkeypatch):
    """A launcher pointing at a module that does not exist fails silently.

    Silently is the operative word: a scheduled task writes its exit code to
    Task Scheduler and nowhere a developer looks, and a .bat file prints a
    traceback into a console window that closes.
    """
    monkeypatch.syspath_prepend(str(_ORCHESTRATOR))
    text = path.read_text(encoding="utf-8", errors="replace")

    broken = []
    for module in sorted(_targets(text)):
        try:
            if importlib.util.find_spec(module) is None:
                broken.append(module)
        except (ImportError, ValueError):
            broken.append(module)

    assert not broken, (
        f"{path.relative_to(_REPO_ROOT)} launches module(s) that cannot be "
        f"imported: {broken}. A rename moved them and this launcher was not "
        "updated with the code."
    )


def test_the_scan_actually_finds_targets():
    """A scan that silently matches nothing would pass forever.

    Without this, deleting the regexes turns the suite above into a no-op that
    reports success, which is the same failure shape as the bug it guards.
    """
    seen: set[str] = set()
    for path in _launcher_files():
        seen |= _targets(path.read_text(encoding="utf-8", errors="replace"))
    assert seen, "no launcher module targets found; the extraction regexes have gone stale"
    assert any(m.startswith("agentmetry") for m in seen)


def test_launch_json_is_parseable_and_names_real_modules():
    """launch.json is gitignored, so CI never sees it and only the operator's
    own machine is affected. That makes it more likely to rot, not less."""
    path = _REPO_ROOT / ".claude" / "launch.json"
    if not path.is_file():
        pytest.skip("no .claude/launch.json on this machine")
    config = json.loads(path.read_text(encoding="utf-8"))
    assert config.get("configurations"), "launch.json has no configurations"
