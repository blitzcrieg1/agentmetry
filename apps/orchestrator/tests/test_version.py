"""Version provenance — B1 from the 2026-07-24 release-readiness review.

Three copies of the version had drifted apart: `pyproject.toml` and the API
both said 0.2.0 while `v0.2.1` was tagged and shipped, so an installed build
misreported which rules produced its evidence. `core/version.py` is now the
only place the number lives; these tests keep it that way.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from agentmetry.core.version import __version__

_ORCHESTRATOR = Path(__file__).resolve().parents[1]
_REPO = _ORCHESTRATOR.parents[1]

_SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+].+)?$")


def test_version_is_semver():
    assert _SEMVER.match(__version__), __version__


def test_pyproject_takes_its_version_from_the_module():
    """A literal `version = "..."` here is exactly how the drift happened."""
    data = tomllib.loads((_ORCHESTRATOR / "pyproject.toml").read_text(encoding="utf-8"))
    assert "version" in data["project"].get("dynamic", []), "version must stay dynamic"
    assert "version" not in data["project"], "hard-coded version reintroduces drift"
    assert data["tool"]["hatch"]["version"]["path"] == "agentmetry/core/version.py"


def test_api_advertises_the_module_version():
    from agentmetry.api.main import app

    assert app.version == __version__


def test_evidence_pack_records_the_producing_version():
    from datetime import date

    from agentmetry.core.audit.evidence_pack import build_evidence_pack

    pack = build_evidence_pack(date(2000, 1, 1), date(2000, 1, 2))
    assert pack["meta"]["producer"] == f"agentmetry-orchestrator/{__version__}"


def test_changelog_documents_the_current_version():
    """The newest released CHANGELOG section must match what we ship.

    Bumping `core/version.py` without a CHANGELOG entry is how a release goes
    out with no record of what changed in it.
    """
    text = (_REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    released = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", text, re.MULTILINE)
    assert released, "CHANGELOG has no released sections"
    assert released[0] == __version__, (
        f"core/version.py is {__version__} but the newest CHANGELOG "
        f"section is {released[0]}"
    )


def test_changelog_unreleased_section_exists():
    text = (_REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [Unreleased]" in text
