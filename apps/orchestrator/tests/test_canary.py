"""Planted decoys must be detectable, reversible, and must never touch a real key."""

import re

import pytest

from agentmetry.core import canary
import agentmetry.core.audit.dlp.loader as loader_mod
from agentmetry.core.audit.dlp.loader import load_dlp_rules


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """Point the whole feature at a temporary home.

    `HOME`, `STATE_DIR`, `RULES_FILE` and the loader's `CANARY_RULES_DIR` are
    module attributes precisely so this can be done without touching the
    developer's real ~/.aws.
    """
    home = tmp_path / "home"
    home.mkdir()
    state = tmp_path / "canary"
    monkeypatch.setattr(canary, "HOME", home)
    monkeypatch.setattr(canary, "STATE_DIR", state)
    monkeypatch.setattr(canary, "STATE_FILE", state / "state.json")
    monkeypatch.setattr(canary, "RULES_FILE", state / "rules.yaml")
    monkeypatch.setattr(loader_mod, "CANARY_RULES_DIR", state)
    return home


def test_plant_aws_appends_a_profile_and_registers_a_rule(sandbox):
    record = canary.plant(kind="aws", scope="home")

    creds = sandbox / ".aws" / "credentials"
    assert creds.exists()
    body = creds.read_text(encoding="utf-8")
    assert f"[{record['name']}]".replace(record["name"], "agentmetry-canary-1") in body

    rules = canary._load_rules()["rules"]
    assert [r["id"] for r in rules] == ["canary_aws-home-1"]
    # The rule is anchored on the planted value, not on a broad prefix.
    assert re.escape(record["values"][0]) in rules[0]["pattern"]
    assert canary.MARK not in rules[0]["pattern"]


def test_plant_refuses_to_touch_an_existing_profile(sandbox):
    creds = sandbox / ".aws" / "credentials"
    creds.parent.mkdir(parents=True)
    creds.write_text("[agentmetry-canary-1]\naws_access_key_id = REALVALUE\n")

    with pytest.raises(SystemExit):
        canary.plant(kind="aws", scope="home")

    assert "REALVALUE" in creds.read_text(encoding="utf-8")


def test_remove_deletes_the_file_it_created(sandbox):
    canary.plant(kind="aws", scope="home")
    creds = sandbox / ".aws" / "credentials"
    assert creds.exists()

    canary.remove("aws-home-1")

    # The file did not exist before planting, so it is gone again.
    assert not creds.exists()
    assert canary._load_rules()["rules"] == []


def test_remove_keeps_content_that_was_there_before(sandbox, tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".env").write_text("EXISTING=1\n")

    record = canary.plant(kind="env", scope="project", project=project)
    assert "EXISTING=1" in (project / ".env").read_text(encoding="utf-8")

    canary.remove(record["name"])
    assert (project / ".env").read_text(encoding="utf-8") == "EXISTING=1\n"


def test_remove_refuses_when_the_file_was_edited_afterwards(sandbox):
    canary.plant(kind="aws", scope="home")
    creds = sandbox / ".aws" / "credentials"
    creds.write_text(creds.read_text(encoding="utf-8") + "\n# hand edit\n")

    with pytest.raises(SystemExit):
        canary.remove("aws-home-1")


def test_forget_drops_bookkeeping_without_touching_the_file(sandbox):
    canary.plant(kind="aws", scope="home")
    creds = sandbox / ".aws" / "credentials"
    creds.write_text(creds.read_text(encoding="utf-8") + "\n# hand edit\n")

    canary.forget("aws-home-1")

    assert creds.exists()
    assert "# hand edit" in creds.read_text(encoding="utf-8")
    assert canary.list_planted() == []
    assert canary._load_rules()["rules"] == []


def test_env_decoy_needs_a_project(sandbox):
    with pytest.raises(SystemExit):
        canary.plant(kind="env", scope="project", project=None)


def test_loader_merges_planted_rules_after_the_manifest(sandbox, tmp_path):
    canary.plant(kind="aws", scope="home")
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text('version: "1.0"\nrules: []\n', encoding="utf-8")

    rules = load_dlp_rules(manifest)

    assert len(rules) == 1
    assert rules[0].category == "canary"
    assert rules[0].severity == "critical"


def test_loader_ignores_canary_dir_when_absent(sandbox, tmp_path, monkeypatch):
    monkeypatch.setattr(loader_mod, "CANARY_RULES_DIR", tmp_path / "nope")
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text('version: "1.0"\nrules: []\n', encoding="utf-8")

    assert load_dlp_rules(manifest) == []
