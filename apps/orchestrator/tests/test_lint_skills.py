"""Skill YAML governance linter — shipped skills must pass invariants."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
LINT_SCRIPT = _REPO / "apps" / "orchestrator" / "scripts" / "lint_skills.py"


def test_shipped_skills_pass_governance_lint():
    result = subprocess.run(
        [sys.executable, str(LINT_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=_REPO / "apps" / "orchestrator",
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "OK" in result.stdout


def test_lint_catches_allowlist_violation(tmp_path: Path):
    bad = tmp_path / "bad_skill.yaml"
    bad.write_text(
        "name: bad_skill\ngraph: pipeline\ntools: []\n"
        "node_tools:\n  step:\n    - tool: vault_fs.read_note\n      args: {}\n",
        encoding="utf-8",
    )
    spec = importlib.util.spec_from_file_location("lint_skills", LINT_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    errors = mod.lint_file(bad)
    assert any("vault_fs.read_note" in e for e in errors)
