"""Tests for the edits_ci_config trait (#317).

CI/CD configuration decides what runs when code lands — which commands
execute, with which secrets, on whose machines. An agent that rewrites a
pipeline file is programming every later push, which is why the issue
names the write together with the push. The trait is the write half, the
same shape as edits_self_config: the push already carries its own signal
(`git_exfil`), and pairing two events is a rule's job. These tests pin
both halves of the write: the destinations that must earn it (Write tool,
patch bodies, shell writes aimed at the path) and the lookalikes that
must not (reads, pushes on their own, prose about the path).
"""

from __future__ import annotations

import pytest

from agentmetry.core.audit.detection.traits import (
    KNOWN_TRAITS,
    classify_command,
    classify_tool_call,
)
from agentmetry.core.audit.mitre import get_mitre_mapping


# --- the Write tool ----------------------------------------------------------


def test_the_trait_is_in_the_vocabulary():
    assert "edits_ci_config" in KNOWN_TRAITS


def test_write_to_github_workflows_fires():
    assert classify_tool_call("Write", "/srv/repo/.github/workflows/ci.yml") == ["edits_ci_config"]
    assert classify_tool_call("Edit", "repo/.github/workflows/release.yaml") == ["edits_ci_config"]
    assert classify_tool_call("Write", "C:\\repo\\.github\\workflows\\ci.yml") == ["edits_ci_config"]


@pytest.mark.parametrize(
    "path",
    [
        "~/.gitlab-ci.yml",
        "/srv/repo/.gitlab-ci.yaml",
        "/srv/repo/.circleci/config.yml",
        "/srv/repo/.circleci/config.yaml",
        "Jenkinsfile",
        "/srv/repo/Jenkinsfile",
        "azure-pipelines.yml",
        "/srv/repo/azure-pipelines.yaml",
        "bitbucket-pipelines.yml",
        ".travis.yml",
        ".drone.yml",
        ".drone.yaml",
    ],
)
def test_write_to_each_pipeline_family_fires(path):
    assert classify_tool_call("Write", path) == ["edits_ci_config"]


def test_patch_body_naming_the_path_fires():
    body = "*** Begin Patch\n*** Update File: .github/workflows/ci.yml\n@@\n+x\n*** End Patch"
    assert classify_tool_call("apply_patch", body) == ["edits_ci_config"]


@pytest.mark.parametrize("key", ["command", "patch", "input", "value"])
def test_patch_header_counts_as_destination_in_both_classifiers(key):
    patch = "*** Begin Patch\n*** Add File: .gitlab-ci.yml\n+x\n*** End Patch"
    evidence = {key: patch}
    assert classify_tool_call("codex.apply_patch", evidence) == ["edits_ci_config"]
    assert get_mitre_mapping("codex.apply_patch", evidence)["technique_id"] == "T1562"


def test_patch_prose_naming_a_ci_path_stays_quiet():
    patch = (
        "*** Begin Patch\n*** Update File: docs/ci.md\n@@\n"
        "+*** Update File: .github/workflows/ci.yml\n*** End Patch"
    )
    assert classify_tool_call("apply_patch", patch) == []
    mapping = get_mitre_mapping("apply_patch", {"command": patch})
    assert mapping is None or mapping["technique_id"] != "T1562"


def test_structured_write_classifies_the_destination_only():
    evidence = {"target_file": ".github/workflows/ci.yml", "content": "name: ci"}
    assert classify_tool_call("Write", evidence) == ["edits_ci_config"]
    assert get_mitre_mapping("Write", evidence)["technique_id"] == "T1562"
    assert classify_tool_call("Write", {"path": "docs/ci.md", "content": evidence["target_file"]}) == []


def test_write_to_lookalike_paths_stays_quiet():
    assert classify_tool_call("Write", "/srv/repo/.github/workflows/ci.yml.bak") == []
    assert classify_tool_call("Write", "/srv/repo/workflows/ci.yml") == []
    assert classify_tool_call("Write", "/srv/repo/.github/actions/ci.yml") == []
    assert classify_tool_call("Write", "/srv/repo/.github/workflows/nested/ci.yml") == []
    assert classify_tool_call("Write", "/srv/repo/.github/workflows/README.md") == []
    assert classify_tool_call("Write", "/srv/repo/docker-compose.yml") == []
    assert classify_tool_call("Write", "/srv/repo/myJenkinsfile") == []
    assert classify_tool_call("Write", "/srv/repo/azure-pipelines.yml/notes") == []


def test_reading_a_pipeline_file_is_not_editing_it():
    assert "edits_ci_config" not in classify_tool_call("Read", ".github/workflows/ci.yml")


# --- shell writes --------------------------------------------------------------


def test_redirect_into_a_pipeline_file_fires():
    assert "edits_ci_config" in classify_command("cat wf.yml > .github/workflows/ci.yml")
    assert "edits_ci_config" in classify_command("echo 'x' >> /srv/repo/.gitlab-ci.yml")


def test_tee_in_place_sed_dd_and_copy_destination_fire():
    assert "edits_ci_config" in classify_command("tee .gitlab-ci.yml < ci.yml")
    assert "edits_ci_config" in classify_command("sed -i 's/\"a\"/\"b\"/' azure-pipelines.yml")
    assert "edits_ci_config" in classify_command("dd if=/tmp/x of=$HOME/.drone.yml")
    assert "edits_ci_config" in classify_command("cp /tmp/evil.yml .github/workflows/ci.yml")
    assert "edits_ci_config" in classify_command("mv old.yml .travis.yml")


def test_reading_a_pipeline_file_by_command_stays_quiet():
    assert "edits_ci_config" not in classify_command("cat .github/workflows/ci.yml")
    assert "edits_ci_config" not in classify_command("grep -n image .gitlab-ci.yml")
    assert "edits_ci_config" not in classify_command("cp .github/workflows/ci.yml /tmp/backup.yml")


def test_prose_about_the_path_stays_quiet():
    """Single-quoted text is something written, not a file being written."""
    assert "edits_ci_config" not in classify_command("echo 'edit .github/workflows/ci.yml by hand'")


def test_quoted_shell_destination_and_quoted_prose():
    command = "cp ci.yml '/tmp/example project/.github/workflows/ci.yml' # local copy"
    assert "edits_ci_config" in classify_command(command)
    assert get_mitre_mapping("Bash", {"command": command})["technique_id"] == "T1562"
    for prose in (
        'printf "%s" "redirect > .github/workflows/ci.yml"',
        "printf data # comment; redirect > .github/workflows/ci.yml",
    ):
        assert "edits_ci_config" not in classify_command(prose)
        assert get_mitre_mapping("Bash", prose)["technique_id"] != "T1562"


def test_a_push_alone_does_not_earn_the_trait():
    """The push is the second half of the signal, and it already has one.

    Pairing the write with a later push is a sequence rule's job; the trait
    must not fire on the push itself, or every ordinary push would carry it.
    """
    traits = classify_command("git push origin main")
    assert "git_exfil" in traits
    assert "edits_ci_config" not in traits


# --- the MITRE mapper agrees -----------------------------------------------------


def test_mapper_upgrades_a_ci_config_write_to_t1562():
    mapping = get_mitre_mapping("Write", {"file_path": ".github/workflows/ci.yml"})
    assert mapping is not None
    assert mapping["technique_id"] == "T1562"
    assert mapping["tactic_id"] == "TA0005"


def test_mapper_leaves_an_ordinary_write_alone():
    mapping = get_mitre_mapping("Write", {"file_path": "src/app.py"})
    assert mapping is not None
    assert mapping["technique_id"] != "T1562"


def test_mapper_ignores_the_path_in_written_content():
    """Prose in the file body naming the path is not a write to that path."""
    mapping = get_mitre_mapping(
        "Write",
        {"file_path": "docs/ci.md", "content": "edit .github/workflows/ci.yml to add the job"},
    )
    assert mapping is not None
    assert mapping["technique_id"] != "T1562"
