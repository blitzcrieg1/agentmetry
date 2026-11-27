"""Test optional canary matching and rollback with synthetic files."""

import json
import os
import re

import pytest

from agentmetry.core import canary, managed_policy
from agentmetry.core.audit.dlp import loader


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """Keep the inventory and all canary targets inside the test directory."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(canary, "HOME", home)
    monkeypatch.setattr(canary, "STATE_FILE", tmp_path / "canary" / "state.json")
    return home


def test_plant_aws_appends_profile_and_registers_literal_rule(sandbox):
    record = canary.plant(kind="aws", scope="home")
    creds = sandbox / ".aws" / "credentials"
    assert "[agentmetry-canary-1]" in creds.read_text(encoding="utf-8")
    rules = loader.load_dlp_rules(loader._BUNDLED_MANIFEST)
    rule = rules[-1]
    assert rule.id == "canary_aws-home-1"
    assert rule.category == "canary"
    assert rule.severity == "critical"
    assert re.escape(record["values"][0]) in rule.pattern
    assert canary.MARK not in rule.pattern


def test_plant_refuses_to_touch_existing_profile(sandbox):
    creds = sandbox / ".aws" / "credentials"
    creds.parent.mkdir()
    original = b"[ agentmetry-canary-1 ]\naws_access_key_id = PLACEHOLDER\n"
    creds.write_bytes(original)
    with pytest.raises(SystemExit, match="already exists"):
        canary.plant(kind="aws", scope="home")
    assert creds.read_bytes() == original


def test_remove_deletes_file_it_created(sandbox):
    canary.plant(kind="aws", scope="home")
    creds = sandbox / ".aws" / "credentials"
    assert creds.exists()
    canary.remove("aws-home-1")
    assert not creds.exists()
    assert canary.list_planted() == []


def test_remove_preserves_original_bytes_and_file_identity(sandbox, tmp_path):
    target = tmp_path / ".env"
    original = b"# synthetic \x81\r\nEXISTING=1\r\n"
    target.write_bytes(original)
    identity = target.stat()
    record = canary.plant(kind="env", scope="project", project=tmp_path)
    assert target.read_bytes().startswith(original)
    canary.remove(record["name"])
    assert target.read_bytes() == original
    assert os.path.samestat(target.stat(), identity)
    assert target.stat().st_mode == identity.st_mode


def test_remove_refuses_an_edited_prefix(sandbox, tmp_path):
    target = tmp_path / ".env"
    original = b"EXISTING=1\n"
    target.write_bytes(original)
    record = canary.plant(kind="env", scope="project", project=tmp_path)
    edited = target.read_bytes().replace(b"EXISTING=1", b"EXISTING=2")
    target.write_bytes(edited)
    with pytest.raises(SystemExit, match="target changed"):
        canary.remove(record["name"])
    assert target.read_bytes() == edited
    assert len(canary.list_planted()) == 1


def test_forget_drops_bookkeeping_without_touching_file(sandbox):
    canary.plant(kind="aws", scope="home")
    creds = sandbox / ".aws" / "credentials"
    edited = creds.read_bytes() + b"\n# hand edit\n"
    creds.write_bytes(edited)
    canary.forget("aws-home-1")
    assert creds.read_bytes() == edited
    assert canary.list_planted() == []


def test_env_decoy_needs_existing_project(sandbox, tmp_path):
    with pytest.raises(SystemExit, match="existing project"):
        canary.plant(kind="env", scope="project", project=tmp_path / "missing")


def test_bundled_rules_survive_bad_optional_state(sandbox):
    manifest = loader._BUNDLED_MANIFEST
    baseline = loader.load_dlp_rules(manifest)
    canary.STATE_FILE.parent.mkdir()
    canary.STATE_FILE.write_text('{"decoys": [{"name": "invalid"}]}', encoding="utf-8")
    assert loader.load_dlp_rules(manifest) == baseline
    with pytest.raises(SystemExit, match="inventory"):
        canary.list_planted()


def test_canary_rules_never_augment_custom_or_managed_policy(sandbox, tmp_path, monkeypatch):
    canary.plant(kind="aws", scope="home")
    manifest = tmp_path / "custom.yaml"
    manifest.write_text('rules: []\n', encoding="utf-8")
    assert loader.load_dlp_rules(manifest) == []

    monkeypatch.setattr(
        managed_policy, "load_policy", lambda: managed_policy.ManagedPolicy(locked={"dlp_mode": "block"})
    )
    assert all(rule.category != "canary" for rule in loader.load_dlp_rules(loader._BUNDLED_MANIFEST))
    with pytest.raises(SystemExit, match="unmanaged"):
        canary.plant(kind="env", scope="project", project=tmp_path)
    assert not (tmp_path / ".env").exists()


def test_observed_literal_matches_but_path_only_does_not(sandbox, tmp_path):
    from agentmetry.core.audit.dlp.scanner import reset_rules, scan

    record = canary.plant(kind="env", scope="project", project=tmp_path)
    reset_rules()
    try:
        assert not scan("Read", {"path": record["path"]}, mode="log").matched
        result = scan("Write", {"content": record["values"][0]}, mode="log")
        assert result.match.rule_id == record["rule_id"]
    finally:
        reset_rules()


def _fail_write(*_args):
    raise OSError("synthetic state write failure")


def test_plant_never_writes_target_if_journal_cannot_be_saved(sandbox, tmp_path, monkeypatch):
    target = tmp_path / ".env"
    target.write_bytes(b"ORIGINAL=1\n")
    monkeypatch.setattr(canary, "_save_records", _fail_write)
    with pytest.raises(SystemExit, match="could not finish"):
        canary.plant(kind="env", scope="project", project=tmp_path)
    assert target.read_bytes() == b"ORIGINAL=1\n"
    assert canary.list_planted() == []


@pytest.mark.parametrize("bytes_written", [1, None])
def test_partial_or_complete_append_remains_recoverable(sandbox, tmp_path, monkeypatch, bytes_written):
    target = tmp_path / ".env"
    original = b"# demonstration \xab\r\nORIGINAL=1\r\n"
    target.write_bytes(original)
    write_append = canary._write_append

    def interrupted_append(path, previous, block):
        write_append(path, previous, block[:bytes_written])
        raise OSError("synthetic interruption after appending")

    with monkeypatch.context() as scope:
        scope.setattr(canary, "_write_append", interrupted_append)
        with pytest.raises(SystemExit, match="could not finish"):
            canary.plant(kind="env", scope="project", project=tmp_path)
    record, = canary.list_planted()
    assert record["pending"]
    assert target.read_bytes() != original
    canary.remove(record["name"])
    assert target.read_bytes() == original
    assert canary.list_planted() == []


def test_remove_retry_after_state_save_failure(sandbox, tmp_path, monkeypatch):
    target = tmp_path / ".env"
    original = b"ORIGINAL=1\n"
    target.write_bytes(original)
    record = canary.plant(kind="env", scope="project", project=tmp_path)
    with monkeypatch.context() as scope:
        scope.setattr(canary, "_save_records", _fail_write)
        with pytest.raises(SystemExit, match="could not finish"):
            canary.remove(record["name"])
    assert target.read_bytes() == original
    assert len(canary.list_planted()) == 1
    canary.remove(record["name"])
    assert canary.list_planted() == []


def test_target_with_multiple_links_is_refused(sandbox, tmp_path):
    original = tmp_path / "synthetic.txt"
    original.write_bytes(b"ORIGINAL=1\n")
    try:
        os.link(original, tmp_path / ".env")
    except OSError:
        pytest.skip("hard links unavailable in the temporary directory")
    with pytest.raises(SystemExit, match="one link"):
        canary.plant(kind="env", scope="project", project=tmp_path)
    assert original.read_bytes() == b"ORIGINAL=1\n"


def test_inventory_cannot_redirect_aws_remove(sandbox, tmp_path):
    record = canary.plant(kind="aws", scope="home")
    stored = json.loads(canary.STATE_FILE.read_text(encoding="utf-8"))
    unrelated = tmp_path / "synthetic-credentials"
    original = record["appended"].encode("ascii")
    unrelated.write_bytes(original)
    stored["decoys"][0]["path"] = str(unrelated)
    stored["decoys"][0]["where"] = f"{unrelated} [agentmetry-canary-1]"
    canary.STATE_FILE.write_text(json.dumps(stored), encoding="utf-8")
    with pytest.raises(SystemExit, match="outside the expected profile"):
        canary.remove(record["name"])
    assert unrelated.read_bytes() == original


def test_v017_inventory_uses_literal_values_and_preserves_legacy_crlf(sandbox, tmp_path):
    target = tmp_path / ".env"
    original = b"ORIGINAL=1\r\n"
    target.write_bytes(original)
    record = canary.plant(kind="env", scope="project", project=tmp_path)
    record["appended"] = record["appended"].replace("\r\n", "\n")
    record["name"] = "nightly review"
    record["rule_id"] = "canary_nightly review"
    record.pop("previous_sha256")
    record.pop("pending")
    canary.STATE_FILE.write_text(json.dumps({"decoys": [record]}), encoding="utf-8")
    (canary.STATE_FILE.parent / "rules.yaml").write_text("invalid: [", encoding="utf-8")
    assert loader.load_dlp_rules(loader._BUNDLED_MANIFEST)[-1].id == record["rule_id"]
    canary.remove(record["name"])
    assert target.read_bytes() == original
