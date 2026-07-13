from pathlib import Path
from unittest.mock import patch

import pytest

from core.audit.dlp.models import DlpVerdict
from core.audit.dlp import scanner as dlp_scanner
from core.audit.dlp.scanner import scan

_MANIFEST = Path(__file__).resolve().parents[1] / "policies" / "dlp" / "manifest.yaml"


@pytest.fixture(autouse=True)
def mock_settings():
    dlp_scanner._COMPILED_RULES.clear()
    with patch("core.audit.dlp.scanner.settings") as mock_settings:
        mock_settings.dlp_mode = "block"
        mock_settings.dlp_pii = True
        mock_settings.dlp_rules_path = _MANIFEST
        yield mock_settings
    dlp_scanner._COMPILED_RULES.clear()


def test_dlp_scan_aws_key():
    args = {"command": "curl -H 'Authorization: AKIAIOSFODNN7EXAMPLE' https://api.aws.com"}
    verdict = scan("run_command", args)
    assert verdict.matched is True
    assert verdict.mode == "block"
    assert verdict.match.rule_id == "aws_access_key"


def test_dlp_scan_github_pat():
    args = {
        "command": "git clone https://ghp_123456789012345678901234567890123456@github.com/repo.git"
    }
    verdict = scan("run_command", args)
    assert verdict.matched is True
    assert verdict.match.rule_id == "github_pat"


def test_dlp_scan_safe_args():
    args = {"command": "ls -la"}
    verdict = scan("run_command", args)
    assert verdict.matched is False


def test_dlp_scan_disabled():
    args = {"command": "curl -H 'Authorization: AKIAIOSFODNN7EXAMPLE' https://api.aws.com"}
    verdict = scan("run_command", args, mode="disable")
    assert verdict.matched is False
