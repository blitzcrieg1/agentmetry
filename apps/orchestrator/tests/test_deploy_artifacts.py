"""The MDM files are part of the product, so a wording drift fails here.

They are scripts and plists, not a running daemon. This checks the contract
Detect, Remediate, and the package builder claim, and that the signing
example is not a live workflow.
"""

from __future__ import annotations

import plistlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MACOS = ROOT / "deploy" / "macos"
WINDOWS = ROOT / "deploy" / "windows"


def test_launchd_plists_split_daemon_and_user_agent():
    daemon = plistlib.loads((MACOS / "ai.agentmetry.daemon.plist").read_bytes())
    agent = plistlib.loads((MACOS / "ai.agentmetry.agent.plist").read_bytes())
    assert daemon["Label"] == "ai.agentmetry.daemon"
    assert daemon["UserName"] == "root"
    assert daemon["ProgramArguments"] == ["/usr/local/lib/agentmetry/agentmetry-daemon.sh"]
    assert agent["Label"] == "ai.agentmetry.agent"
    assert agent["LimitLoadToSessionType"] == "Aqua"
    assert agent["StartInterval"] == 300
    wrapper = (MACOS / "agentmetry-daemon.sh").read_text(encoding="utf-8")
    assert "--data-dir" in wrapper and "/var/db/agentmetry" in wrapper
    assert "--policy-dir" in wrapper and "/etc/agentmetry" in wrapper
    assert "--user-profile-dir" in wrapper
    user = (MACOS / "agentmetry-user-agent.sh").read_text(encoding="utf-8")
    assert "hooks status" in user and "hooks install" in user
    assert "/var/db/agentmetry" not in user


def test_mdm_profile_locks_sensor_prefs_and_the_login_item():
    profile = plistlib.loads((MACOS / "agentmetry-mdm-profile.mobileconfig").read_bytes())
    payloads = {item["PayloadType"]: item for item in profile["PayloadContent"]}
    sensor = payloads["ai.agentmetry.sensor"]
    assert sensor["dlp_mode"] == "log"
    assert sensor["auth_disabled"] is False
    rules = payloads["com.apple.servicemanagement"]["Rules"]
    assert rules[0]["RuleType"] == "Label"
    assert rules[0]["RuleValue"] == "ai.agentmetry.agent"


def test_pkg_script_signs_from_the_environment_and_embeds_no_secret():
    script = (MACOS / "build_pkg.sh").read_text(encoding="utf-8")
    assert "codesign" in script and "--options runtime" in script
    assert "pkgbuild" in script and "productbuild" in script
    assert "xcrun notarytool" in script
    assert "AGENTMETRY_CODESIGN_IDENTITY" in script
    assert "AGENTMETRY_INSTALLER_IDENTITY" in script
    assert "AGENTMETRY_ALLOW_UNSIGNED" in script
    assert "BEGIN PRIVATE" not in script
    assert "AKIA" not in script


def test_intune_scripts_use_doctor_json_and_icacls_sids():
    detect = (WINDOWS / "Detect-Agentmetry.ps1").read_text(encoding="utf-8")
    assert "agentmetry doctor --json" in detect
    assert "uncovered" in detect and "unknown" in detect
    assert "orchestrator_reachable" in detect
    remediate = (WINDOWS / "Remediate-Agentmetry.ps1").read_text(encoding="utf-8")
    assert "agentmetry hooks install" in remediate
    assert "hook_remediation" in remediate
    assert "exit 0" in remediate
    protect = (WINDOWS / "Protect-AgentmetryData.ps1").read_text(encoding="utf-8")
    assert "icacls" in protect
    assert "S-1-5-18" in protect
    assert "S-1-5-32-544" in protect
    assert "S-1-5-32-545" in protect
    assert "policy.yaml" in protect and "trail" in protect


def test_signing_example_is_not_a_live_workflow():
    example = ROOT / "docs" / "deploy" / "examples" / "windows-trusted-signing.yml"
    text = example.read_text(encoding="utf-8")
    assert "azure/trusted-signing-action@v0" in text
    assert "azure/login@v2" in text
    assert "id-token: write" in text
    assert "client_secret" not in text
    assert "secrets." not in text
    live = list((ROOT / ".github" / "workflows").glob("*sign*"))
    assert live == []
