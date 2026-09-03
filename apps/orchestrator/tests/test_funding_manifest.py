"""`funding.json` quotes numbers about this repository. Numbers rot.

The manifest is published to the FLOSS/fund directory and read by people
deciding whether to give money, which makes it the worst place in the project
for a stale figure. `CONTRIBUTORS.md` proved the point the week this was
written: it advertised commit counts that its own printed command did not
produce, and nothing failed.

`test_readme_claims.py` already does this for the README and `test_version.py`
for the version string. This does the same for the manifest, so a figure that
drifts fails here instead of in front of a funder.

Only the claims that a command can settle are pinned. The download count and
the test count are stamped with a date in the manifest itself and are left
alone, because a number that says when it was true does not become false.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agentmetry.core.audit.detection.benchmark import load_corpus
from agentmetry.core.version import __version__

MANIFEST = Path(__file__).resolve().parents[3] / "funding.json"


def _manifest() -> dict:
    if not MANIFEST.is_file():
        pytest.skip(f"funding.json not found at {MANIFEST}")
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _project_description() -> str:
    projects = _manifest().get("projects") or []
    assert projects, "funding.json lists no projects"
    return projects[0]["description"]


def test_the_manifest_is_valid_json_with_the_required_shape():
    """Cheap, and it catches the edit that breaks the directory listing."""
    manifest = _manifest()
    for key in ("entity", "funding"):
        assert key in manifest, f"funding.json is missing the required {key!r} object"
    funding = manifest["funding"]
    assert funding.get("channels"), "no funding channels declared"
    assert funding.get("plans"), "no funding plans declared"

    channels = {c["guid"] for c in funding["channels"]}
    for plan in funding["plans"]:
        unknown = set(plan["channels"]) - channels
        assert not unknown, f"plan {plan['guid']!r} points at undeclared channel(s) {unknown}"


def test_quoted_version_matches_the_package():
    quoted = re.search(r"version (\d+\.\d+\.\d+) on PyPI", _project_description())
    assert quoted, "funding.json no longer quotes a version; update this test or the manifest"
    assert quoted.group(1) == __version__, (
        "funding.json quotes a different version than the package ships"
    )


def test_quoted_benchmark_case_count_matches_the_corpus():
    quoted = re.search(r"(\d+) case detection benchmark", _project_description())
    assert quoted, "funding.json no longer quotes a case count; update this test or the manifest"
    assert int(quoted.group(1)) == len(load_corpus()), (
        "funding.json quotes a different case count than the corpus holds"
    )


def test_declared_licence_matches_the_package_metadata():
    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    declared = re.search(r'license\s*=\s*\{\s*text\s*=\s*"([^"]+)"', pyproject)
    assert declared, "pyproject.toml no longer declares a licence in the expected form"

    licences = _manifest()["projects"][0]["licenses"]
    assert licences == [f"spdx:{declared.group(1)}"], (
        "funding.json declares a different licence than the package does"
    )
