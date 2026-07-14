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


# Real tool names observed in the live trail that used to fall through the map.
# Each miss here is a detection that silently never fires.

def test_mitre_maps_real_ide_tool_spellings():
    cases = {
        "cursor.Read": "T1005",
        "cursor.Grep": "T1005",
        "cursor.Write": "T1565",
        "cursor.Shell": "T1059",
        "cursor.SearchAndReplace": "T1565",
        "MultiEdit": "T1565",
        "Bash": "T1059.004",
        "Glob": "T1083",
        "antigravity.view_file": "T1005",
        "shell.run": "T1059",
    }
    for tool, technique in cases.items():
        mapping = get_mitre_mapping(tool)
        assert mapping is not None, f"{tool} is unmapped"
        assert mapping["technique_id"] == technique, tool


def test_mitre_delete_is_data_destruction():
    """cursor.Delete was unmapped — the highest-severity impact, silently missed."""
    for tool in ("cursor.Delete", "vault_fs.delete_file"):
        m = get_mitre_mapping(tool)
        assert m["tactic_id"] == "TA0040"
        assert m["technique_id"] == "T1485"


def test_mitre_network_tools_are_c2_so_exfil_can_fire():
    """WebFetch/WebSearch must be TA0011 or credential-exfil can never fire."""
    for tool in ("WebFetch", "WebSearch", "shell.curl", "web_fetch"):
        m = get_mitre_mapping(tool)
        assert m is not None, f"{tool} is unmapped"
        assert m["tactic_id"] == "TA0011", tool


# --- DLP ---------------------------------------------------------------------

def test_luhn_accepts_valid_card_rejects_random():
    assert _luhn_ok("4111111111111111") is True    # valid Visa test number
    assert _luhn_ok("1234567812345678") is False    # random 16 digits
