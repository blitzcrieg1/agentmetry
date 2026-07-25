"""Single source of truth for the Agentmetry version.

`pyproject.toml` reads this file (hatchling `[tool.hatch.version]`), the API
advertises it, and `tests/test_version.py` asserts it matches the newest
released CHANGELOG entry. Evidence packs record the producing version, so a
version that disagrees with the tag is a provenance defect, not cosmetics.

Bump this here and add the matching CHANGELOG section in the same commit.
"""

from __future__ import annotations

__version__ = "0.2.1"
