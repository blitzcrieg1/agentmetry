"""Tests for MITRE mapping upgrades and DLP scanning."""

from __future__ import annotations

from core.audit.mitre import get_mitre_mapping
from core.audit.dlp.scanner import _luhn_ok


# --- MITRE -------------------------------------------------------------------

def test_mitre_tool_name_maps_structured():
    m = get_mitre_mapping("vault_fs.read_file")
    assert m is not None
    assert m["tactic_id"] == "TA0009"          # Collection
    assert m["technique_id"] == "T1005"
    assert "tactic" in m and "technique" in m  # human labels retained


def test_mitre_credential_access_upgrade_on_private_key():
    """The flagship signal: reading a private key is Credential Access, not Collection."""
    m = get_mitre_mapping("shell.run", "cat ~/.ssh/id_rsa")
    assert m["tactic_id"] == "TA0006"          # Credential Access
    assert m["technique_id"] == "T1552.004"    # Private Keys


def test_mitre_credential_file_upgrade():
    m = get_mitre_mapping("read_file", {"path": "/home/x/.aws/credentials"})
    assert m["tactic_id"] == "TA0006"
    assert m["technique_id"] == "T1552.001"


def test_mitre_network_tool_maps_c2():
    m = get_mitre_mapping("shell.curl")
    assert m["tactic_id"] == "TA0011"          # Command and Control
    assert m["technique_id"] == "T1071.001"


def test_mitre_no_false_loose_match():
    """The old bidirectional endswith matched 'file' to 'read_file'; must not now."""
    assert get_mitre_mapping("file") is None
    assert get_mitre_mapping("some.unknown_tool") is None


def test_mitre_method_suffix_match():
    assert get_mitre_mapping("cursor.run_command")["technique_id"] == "T1059"


# --- DLP ---------------------------------------------------------------------

def test_luhn_accepts_valid_card_rejects_random():
    assert _luhn_ok("4111111111111111") is True    # valid Visa test number
    assert _luhn_ok("1234567812345678") is False    # random 16 digits
