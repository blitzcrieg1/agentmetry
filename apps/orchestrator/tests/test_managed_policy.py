"""Managed policy: a fleet lock wins, and only a file the developer cannot edit locks.

The first draft of this loader decided trust by parsing `icacls` text. It read
`BUILTIN\\Users:(CI)(WD,AD,WEA,WA)`, the entry every new folder under
`C:\\ProgramData` inherits, as one unknown right, so a standard user could plant
a trusted policy the SYSTEM service then applied. It also refused a
legitimate file on a German Windows, where SYSTEM is `NT-AUTORITÄT\\SYSTEM`.
Trust is now decided from SIDs and access masks, and these tests pin both.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from agentmetry.core import managed_policy as mp
from agentmetry.core.managed_policy import Ace, PolicySyntax, Untrusted

USER_SID = "S-1-5-21-1111111111-2222222222-3333333333-1001"
USERS_SID = "S-1-5-32-545"


# ----------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------


def test_a_flat_policy_parses():
    doc = mp.parse_policy_yaml(
        "# fleet policy\n"
        "schema: 1\n"
        "dlp_mode: block   # no exceptions\n"
        "dlp_pii: off\n"
        "heartbeat_seconds: 300\n"
        "trusted_hosts: 'agentmetry.corp # internal'\n"
    )
    assert doc == {
        "schema": 1, "dlp_mode": "block", "dlp_pii": False,
        "heartbeat_seconds": 300, "trusted_hosts": "agentmetry.corp # internal",
    }


@pytest.mark.parametrize("text", [
    "dlp_mode:\n  nested: block\n",
    "  dlp_mode: block\n",
    "- dlp_mode\n",
    "dlp_mode: [block]\n",
    "dlp_mode: &a block\n",
    "dlp_mode: |\n",
    "dlp_mode: block\ndlp_mode: log\n",
    "DLP_MODE: block\n",
    "dlp_mode block\n",
    "dlp_mode: 'block\n",
])
def test_anything_but_flat_scalars_is_refused(text):
    with pytest.raises(PolicySyntax):
        mp.parse_policy_yaml(text)


def test_one_bad_value_refuses_the_whole_document():
    """A typo must not lock dlp_pii while silently dropping the dlp_mode the
    admin cared about."""
    with pytest.raises(PolicySyntax, match="dlp_mode"):
        mp.normalize_document({"dlp_pii": True, "dlp_mode": "blokc"})


def test_unknown_keys_are_reported_not_applied():
    values, unknown = mp.normalize_document({"dlp_mode": "block", "future_key": 1})
    assert values == {"dlp_mode": "block"}
    assert unknown == ("future_key",)


@pytest.mark.parametrize("doc", [
    {"schema": 2, "dlp_mode": "block"},
    {"data_dir": "relative/data"},
    {"audit_sink": "file,carrier-pigeon"},
    {"heartbeat_seconds": -1},
    {"dlp_pii": "maybe"},
    {"trusted_hosts": ["a", "b"]},
])
def test_bad_documents_are_refused(doc):
    with pytest.raises(PolicySyntax):
        mp.normalize_document(doc)


def test_registry_style_values_coerce():
    """REG_DWORD booleans and a sink list, as an admin would write them."""
    values, _ = mp.normalize_document({"dlp_pii": 0, "auth_disabled": 1, "audit_sink": "File, Splunk"})
    assert values == {"dlp_pii": False, "auth_disabled": True, "audit_sink": "file,splunk"}


# ----------------------------------------------------------------------
# Trust: Windows, decided from SIDs
# ----------------------------------------------------------------------


def _admin_aces(*extra: Ace) -> list[Ace]:
    return [Ace(0, 0, 0x1F01FF, mp.SYSTEM_SID), Ace(0, 0, 0x1F01FF, mp.ADMINISTRATORS_SID),
            Ace(0, 0, 0x1200A9, USERS_SID), *extra]


def test_a_system_owned_file_users_can_only_read_is_trusted():
    mp.judge_windows("policy.yaml", mp.SYSTEM_SID, _admin_aces(), mp.FILE_WRITE_MASK)


def test_the_programdata_default_lets_users_plant_a_file_and_is_refused():
    """`(CI)(WD,AD,WEA,WA)` is mask 0x116. icacls prints it as one parenthesis."""
    with pytest.raises(Untrusted, match=USERS_SID):
        mp.judge_windows("Agentmetry", mp.SYSTEM_SID, _admin_aces(Ace(0, 0, 0x116, USERS_SID)),
                         mp.DIR_WRITE_MASK)


def test_a_file_the_user_created_is_refused_on_owner_alone():
    with pytest.raises(Untrusted, match="owned by"):
        mp.judge_windows("policy.yaml", USER_SID, _admin_aces(), mp.FILE_WRITE_MASK)


def test_a_null_dacl_is_refused():
    with pytest.raises(Untrusted, match="no DACL"):
        mp.judge_windows("policy.yaml", mp.SYSTEM_SID, None, mp.FILE_WRITE_MASK)


def test_owner_rights_grants_only_to_the_privileged_owner():
    mp.judge_windows("policy.yaml", mp.SYSTEM_SID, _admin_aces(Ace(0, 0, 0x1F01FF, mp.OWNER_RIGHTS_SID)),
                     mp.FILE_WRITE_MASK)


def test_inherit_only_and_deny_aces_do_not_count():
    mp.judge_windows("policy.yaml", mp.ADMINISTRATORS_SID, _admin_aces(
        Ace(0, mp._INHERIT_ONLY, 0x1F01FF, "S-1-3-0"),  # CREATOR OWNER, for children
        Ace(1, 0, 0x1F01FF, USER_SID),  # deny
    ), mp.FILE_WRITE_MASK)


def test_an_ace_layout_the_check_cannot_read_is_refused():
    with pytest.raises(Untrusted, match="type 0x5"):
        mp.judge_windows("policy.yaml", mp.SYSTEM_SID, _admin_aces(Ace(5, 0, 0x2, "")),
                         mp.FILE_WRITE_MASK)


@pytest.mark.skipif(os.name != "nt", reason="Win32 security descriptors")
def test_windows_reads_real_sids():
    """The ctypes path on a file whose ACL every Windows ships the same way."""
    owner, aces = mp._windows_security(path=Path(os.environ["SystemRoot"]) / "System32" / "kernel32.dll")
    assert owner == mp.TRUSTED_INSTALLER_SID
    assert aces and all(a.sid.startswith("S-1-") for a in aces if a.ace_type in (0, 1))


@pytest.mark.skipif(os.name != "nt", reason="Win32 security descriptors")
def test_windows_refuses_a_file_users_can_modify(tmp_path):
    """A real ACL, made the same on every machine. Who owns a new file depends
    on the token: on Windows Server an elevated admin's files belong to
    Administrators, so "a file in my temp" is trusted there, correctly, since
    only an admin could change it. Granting Users modify is refused anywhere."""
    policy = tmp_path / "policy.yaml"
    policy.write_bytes(b"dlp_mode: block\n")
    subprocess.run(["icacls", str(policy), "/grant", f"*{USERS_SID}:M"], check=True, capture_output=True)
    with pytest.raises(Untrusted, match=USERS_SID + "|owned by"):
        mp.read_trusted(policy)


@pytest.mark.skipif(os.name != "nt", reason="Win32 security descriptors")
def test_the_acl_doctor_prints_leaves_the_file_readable(tmp_path):
    """No elevation needed for this half. With `/T` the same command leaves the
    file an empty DACL, and the recorder could not read the policy it trusts."""
    folder = tmp_path / "Agentmetry"
    folder.mkdir()
    policy = folder / "policy.yaml"
    policy.write_bytes(b"dlp_mode: block\n")
    remedy = mp.remediation(str(policy))
    acl = remedy.split("then icacls ", 1)[1].rstrip(".")
    assert "/T" not in acl
    subprocess.run(["icacls", str(folder), "/inheritance:r", "/grant:r", f"*{mp.SYSTEM_SID}:(OI)(CI)F",
                    f"*{mp.ADMINISTRATORS_SID}:(OI)(CI)F", f"*{USERS_SID}:(OI)(CI)RX"],
                   check=True, capture_output=True)
    _owner, aces = mp._windows_security(path=policy)
    # Anything else the platform adds (the CI runner keeps an OWNER RIGHTS
    # entry) must not let another principal write.
    assert {mp.SYSTEM_SID, mp.ADMINISTRATORS_SID, USERS_SID} <= {a.sid for a in aces or []}
    for ace in aces or []:
        if ace.sid not in mp.PRIVILEGED_SIDS | {mp.OWNER_RIGHTS_SID}:
            assert not ace.mask & mp.FILE_WRITE_MASK, ace
    assert policy.read_bytes() == b"dlp_mode: block\n"


def _elevated() -> bool:
    if os.name == "nt":
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    return os.geteuid() == 0


@pytest.mark.skipif(os.name != "nt", reason="Win32 security descriptors")
def test_windows_trusts_a_folder_hardened_the_way_doctor_says(tmp_path):
    """The only test that proves doctor's fix produces a file the check accepts.
    A CI runner is elevated, so there it must run: a skip would hide the one
    environment that can answer."""
    if not _elevated():
        if os.environ.get("CI"):
            pytest.fail("the Windows CI runner is expected to be elevated")
        pytest.skip("needs an elevated Windows token")
    folder = tmp_path / "Agentmetry"
    folder.mkdir()
    policy = folder / "policy.yaml"
    policy.write_bytes(b"dlp_mode: block\n")
    # The order doctor prints: owner first, then the ACL.
    for args in (
        ["/setowner", f"*{mp.ADMINISTRATORS_SID}", "/T"],
        ["/inheritance:r", "/grant:r", f"*{mp.SYSTEM_SID}:(OI)(CI)F",
         f"*{mp.ADMINISTRATORS_SID}:(OI)(CI)F", f"*{USERS_SID}:(OI)(CI)RX"],
    ):
        done = subprocess.run(["icacls", str(folder), *args], capture_output=True, text=True)
        assert done.returncode == 0, f"icacls {' '.join(args)}: {done.stdout}{done.stderr}"
    assert mp.remediation(str(policy)).index("/setowner") < mp.remediation(str(policy)).index("/grant:r")
    assert mp.read_trusted(policy) == b"dlp_mode: block\n"


# ----------------------------------------------------------------------
# Trust: POSIX
# ----------------------------------------------------------------------


def test_posix_wants_root_and_no_group_or_world_write():
    mp.judge_posix("/etc/agentmetry/policy.yaml", 0, 0o644)
    with pytest.raises(Untrusted, match="uid 501"):
        mp.judge_posix("/etc/agentmetry/policy.yaml", 501, 0o644)
    with pytest.raises(Untrusted, match="writable"):
        mp.judge_posix("/etc/agentmetry/policy.yaml", 0, 0o664)


def _linux_acl(*entries: tuple[int, int, int]) -> bytes:
    blob = (2).to_bytes(4, "little")
    for tag, perm, ident in entries:
        blob += tag.to_bytes(2, "little") + perm.to_bytes(2, "little") + ident.to_bytes(4, "little")
    return blob


def test_a_linux_acl_granting_a_user_write_is_caught():
    base = [(0x01, 6, 0xFFFFFFFF), (0x04, 4, 0xFFFFFFFF), (0x20, 4, 0xFFFFFFFF)]
    assert not mp.linux_acl_grants_write(_linux_acl(*base))
    assert not mp.linux_acl_grants_write(_linux_acl(*base, (0x02, 4, 1000)))  # read only
    assert mp.linux_acl_grants_write(_linux_acl(*base, (0x02, 6, 1000)))
    assert mp.linux_acl_grants_write(_linux_acl(*base, (0x08, 2, 100)))


def test_a_mac_acl_allowing_write_is_caught_and_a_deny_is_not():
    deny = "!#acl 1\ngroup:ABCDEFAB-CDEF-ABCD-EFAB-CDEF0000000C:everyone:12:deny:delete\n"
    allow = "!#acl 1\nuser:FFFFEEEE-DDDD-CCCC-BBBB-AAAA000001F5:dev:501:allow:read,write\n"
    assert not mp.mac_acl_grants_write(deny)
    assert mp.mac_acl_grants_write(allow)


@pytest.mark.skipif(os.name == "nt", reason="POSIX ownership")
def test_posix_refuses_a_file_the_user_owns(tmp_path):
    policy = tmp_path / "policy.yaml"
    policy.write_bytes(b"dlp_mode: block\n")
    if os.geteuid() == 0:
        pytest.skip("root owns everything it writes")
    with pytest.raises(Untrusted):
        mp.read_trusted(policy)


@pytest.mark.skipif(os.name == "nt", reason="POSIX ownership")
def test_posix_trusts_a_root_owned_system_file():
    """`/etc/passwd`: root-owned and 0644 on every Unix. On macOS `/etc` is a
    root-owned symlink to `/private/etc`, which is the case the chain allows."""
    assert mp.read_trusted(Path("/etc/passwd"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks")
def test_posix_refuses_a_symlink_at_the_file(tmp_path):
    link = tmp_path / "policy.yaml"
    link.symlink_to("/etc/passwd")
    with pytest.raises(Untrusted):
        mp.read_trusted(link)


# ----------------------------------------------------------------------
# Loading
# ----------------------------------------------------------------------


def _files(tmp_path, **docs: str) -> list[Path]:
    out = []
    for name, text in docs.items():
        path = tmp_path / f"{name}.yaml"
        path.write_text(text, encoding="utf-8")
        out.append(path)
    return out


def _trust_all(path: Path) -> bytes:
    return path.read_bytes()


def test_the_first_source_to_lock_a_key_wins(tmp_path):
    first, second = _files(tmp_path, a="dlp_mode: block\n", b="dlp_mode: log\ndlp_pii: false\n")
    policy = mp.load_policy(locations=[first, second], registry={}, reader=_trust_all)
    assert policy.locked == {"dlp_mode": "block", "dlp_pii": False}


def test_the_registry_wins_and_its_names_are_case_insensitive(tmp_path):
    (path,) = _files(tmp_path, a="dlp_mode: log\n")
    policy = mp.load_policy(locations=[path], registry={"dlp_mode": "block"}, reader=_trust_all)
    assert policy.locked["dlp_mode"] == "block"
    assert policy.sources[0].location == mp.REGISTRY_LOCATION


def test_an_untrusted_file_is_refused_and_recorded_not_read(tmp_path):
    (path,) = _files(tmp_path, a="auth_disabled: true\n")

    def refuse(p: Path) -> bytes:
        raise Untrusted(f"{p} is owned by {USER_SID}")

    policy = mp.load_policy(locations=[path], registry={}, reader=refuse)
    assert policy.locked == {}
    assert [s.location for s in policy.rejected] == [str(path)]
    assert "not trusted" in policy.rejected[0].reason


def test_a_check_that_crashes_is_a_refusal_not_an_exception(tmp_path):
    (path,) = _files(tmp_path, a="dlp_mode: block\n")

    def broken(_p: Path) -> bytes:
        raise AttributeError("acl_get_fd_np")

    policy = mp.load_policy(locations=[path], registry={}, reader=broken)
    assert policy.locked == {} and policy.rejected


def test_absent_files_are_not_sources(tmp_path):
    policy = mp.load_policy(locations=[tmp_path / "nope.yaml"], registry={}, reader=_trust_all)
    assert policy.sources == []


def test_the_policy_dir_adds_a_location_and_never_replaces_one(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTMETRY_POLICY_DIR", str(tmp_path))
    found = mp.managed_locations()
    assert found[-2:] == [tmp_path / "policy.yaml", tmp_path / "policy.plist"]
    assert len(found) > 2


@pytest.mark.skipif(os.name != "nt", reason="Windows known folders")
def test_programdata_comes_from_the_shell_not_the_variable(monkeypatch, tmp_path):
    """`PROGRAMDATA` is the user's to set. Pointing it at an empty folder must
    not make the fleet's real policy disappear."""
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path))
    assert not mp.managed_locations()[0].is_relative_to(tmp_path)


# ----------------------------------------------------------------------
# Applying
# ----------------------------------------------------------------------


def test_locks_overwrite_the_environment_and_its_other_case_spellings():
    env = {"AGENTMETRY_DLP_MODE": "disable", "agentmetry_dlp_mode": "disable", "OTHER": "x"}
    mp.apply_locks(env, mp.ManagedPolicy(locked={"dlp_mode": "block", "dlp_pii": True}))
    assert env == {
        "AGENTMETRY_DLP_MODE": "block",
        "AGENTMETRY_DLP_PII": "true",
        "AGENTMETRY_DLP_RULES_PATH": str(mp._BUILT_IN_RULES["dlp_rules_path"]),
        "OTHER": "x",
    }


def test_a_locked_mode_pins_its_rules_unless_the_rules_are_locked_too():
    """`dlp_mode: block` is undone by pointing the rules at an empty manifest."""
    env = {"AGENTMETRY_TOOL_POLICY_PATH": "/home/dev/allow-everything.yaml"}
    policy = mp.apply_locks(env, mp.ManagedPolicy(locked={"tool_policy_mode": "block"}))
    assert env["AGENTMETRY_TOOL_POLICY_PATH"] == str(mp._BUILT_IN_RULES["tool_policy_path"])
    assert policy.pinned == ["tool_policy_path"]

    env = {}
    custom = str(Path("/opt/fleet/tool.yaml").resolve())
    mp.apply_locks(env, mp.ManagedPolicy(locked={"tool_policy_mode": "block", "tool_policy_path": custom}))
    assert env["AGENTMETRY_TOOL_POLICY_PATH"] == custom


def test_a_locked_data_dir_pins_the_files_inside_it():
    """The hook derives its spool from the trail's path, so one variable could
    otherwise move the evidence out of a locked directory."""
    root = Path("/srv/agentmetry").resolve()
    env = {"AGENTMETRY_AUDIT_EXPORT_PATH": "/home/dev/elsewhere.jsonl"}
    mp.apply_locks(env, mp.ManagedPolicy(locked={"data_dir": str(root)}))
    assert env["AGENTMETRY_DATA_DIR"] == str(root)
    assert env["AGENTMETRY_AUDIT_EXPORT_PATH"] == str(root / "audit-forward.jsonl")
    assert env["AGENTMETRY_DETECTION_DISPOSITION_DB_PATH"] == str(root / "detection_disposition.db")


def test_the_hooks_resolver_sees_the_lock_over_env_and_dotenv(monkeypatch, tmp_path):
    from agentmetry.core.audit import policy_settings as ps

    dotenv = tmp_path / ".env"
    dotenv.write_text("AGENTMETRY_DLP_MODE=disable\n", encoding="utf-8")
    monkeypatch.setattr(ps, "env_path", lambda: dotenv)
    monkeypatch.setenv("AGENTMETRY_DLP_MODE", "disable")
    mp.apply_locks(policy=mp.ManagedPolicy(locked={"dlp_mode": "block"}))
    assert ps.resolve().dlp_mode == "block"


def test_settings_built_after_the_lock_see_it(monkeypatch):
    from agentmetry.core.config import Settings

    monkeypatch.setenv("AGENTMETRY_DLP_MODE", "disable")
    mp.apply_locks(policy=mp.ManagedPolicy(locked={"dlp_mode": "block"}))
    assert Settings().dlp_mode == "block"


_IMPORT_ORDER_PROBE = """
import json, os, sys
from agentmetry.core import managed_policy as mp
mp.load_policy = lambda **_: mp.ManagedPolicy(locked={"dlp_mode": "block"})
from agentmetry.core.config import settings
print(json.dumps([settings.dlp_mode, str(settings.dlp_rules_path)]))
"""


def test_core_config_applies_locks_before_it_builds_settings(tmp_path):
    """The production path: the lock lands at import, before `Settings()`.

    A subprocess, because this suite imports `core.config` long before any
    test runs and turns host policy off to do it.
    """
    env = {**os.environ, "AGENTMETRY_DLP_MODE": "disable",
           "AGENTMETRY_DLP_RULES_PATH": str(tmp_path / "empty.yaml")}
    out = subprocess.run([sys.executable, "-c", _IMPORT_ORDER_PROBE], env=env,
                         capture_output=True, text=True, timeout=60, check=True)
    mode, rules = __import__("json").loads(out.stdout.strip().splitlines()[-1])
    assert mode == "block"
    assert Path(rules) == mp._BUILT_IN_RULES["dlp_rules_path"]


def test_the_hook_applies_locks_before_it_dispatches(monkeypatch):
    from agentmetry.hooks import ingest

    monkeypatch.setenv("AGENTMETRY_DLP_MODE", "disable")
    monkeypatch.setattr(mp, "load_policy", lambda **_: mp.ManagedPolicy(locked={"dlp_mode": "block"}))
    seen = {}

    def hook_main(_name: str) -> int:
        seen["mode"] = os.environ["AGENTMETRY_DLP_MODE"]
        return 0

    monkeypatch.setattr(ingest, "hook_main", hook_main)
    ingest.main(["claude", "hook", "PreToolUse"])
    assert seen["mode"] == "block"


def test_the_cli_lock_beats_the_data_dir_flag(monkeypatch, tmp_path, capsys):
    from agentmetry import cli

    locked = tmp_path / "locked"
    for name in ("AGENTMETRY_DATA_DIR", "AGENTMETRY_AUDIT_EXPORT_PATH", "AGENTMETRY_AUDIT_DB_PATH",
                 "AGENTMETRY_DETECTION_LIVE_DB_PATH", "AGENTMETRY_DETECTION_DISPOSITION_DB_PATH"):
        monkeypatch.setenv(name, "")
    monkeypatch.setattr(cli, "_DATA_DIR", cli._DATA_DIR)
    monkeypatch.setattr(cli, "_PID_FILE", cli._PID_FILE)
    monkeypatch.setattr(mp, "load_policy", lambda **_: mp.ManagedPolicy(locked={"data_dir": str(locked)}))
    import argparse

    args = argparse.Namespace(data_dir=str(tmp_path / "flag"))
    cli._apply_dir_flags(args)
    cli._apply_managed_policy(args)
    assert cli._DATA_DIR == locked
    assert "--data-dir ignored" in capsys.readouterr().err


# ----------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------


def _refused() -> mp.ManagedPolicy:
    return mp.ManagedPolicy(sources=[mp.PolicySource(r"C:\ProgramData\Agentmetry\policy.yaml", False,
                                                     f"not trusted: owned by {USER_SID}")])


def test_a_refused_policy_degrades_the_heartbeat_without_naming_the_user(monkeypatch):
    from agentmetry.core.audit import heartbeat as hb

    monkeypatch.setattr(mp, "load_policy", lambda **_: _refused())
    monkeypatch.setattr(hb, "_spool_depth", lambda: 0)
    event = hb.build_heartbeat_event("2026-10-19T12:00:00+00:00")
    assert event["action"]["outcome"] == "degraded"
    assert "REFUSED" in event["action"]["reason"]
    assert event["heartbeat"]["policy_rejected"] == [r"C:\ProgramData\Agentmetry\policy.yaml"]
    assert USER_SID not in str(event)


def test_doctor_fails_a_refused_policy_and_says_how_to_fix_it(monkeypatch):
    from agentmetry.core.diagnostics import doctor

    monkeypatch.setattr(mp, "load_policy", lambda **_: _refused())
    report = doctor.DoctorReport()
    doctor._check_managed_policy(report)
    (line,) = [f for f in report.findings if f.code == "managed_policy"]
    assert line.severity == "fail"
    assert USER_SID in line.message
    assert ("icacls" in line.message) if os.name == "nt" else ("root-owned" in line.message)


def test_doctor_names_the_locks_and_the_pins(monkeypatch):
    from agentmetry.core.diagnostics import doctor

    policy = mp.ManagedPolicy(locked={"dlp_mode": "block"},
                              sources=[mp.PolicySource("/etc/agentmetry/policy.yaml", True, "trusted", ("dlp_mode",))])
    monkeypatch.setattr(mp, "load_policy", lambda **_: policy)
    report = doctor.DoctorReport()
    doctor._check_managed_policy(report)
    messages = [f.message for f in report.findings if f.code == "managed_policy"]
    assert any("locks dlp_mode" in m for m in messages)
    assert any("dlp_rules_path pinned" in m for m in messages)
