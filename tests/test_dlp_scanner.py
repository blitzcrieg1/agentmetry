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


def test_dlp_scan_huggingface_token():
    args = {"command": "huggingface-cli login --token hf_abcdefghijklmnopqrstuvwxyz1234567890AB"}
    verdict = scan("run_command", args)
    assert verdict.matched is True
    assert verdict.match.rule_id == "huggingface_token"


def test_dlp_scan_tencent_secret_id():
    secret_id = "AKID" + "A" * 32
    args = {"command": f"export TENCENT_SECRET_ID={secret_id}"}
    verdict = scan("run_command", args)
    assert verdict.matched is True
    assert verdict.match.rule_id == "tencent_secret_id"


def test_dlp_scan_chinese_api_key_assignment():
    args = {"command": "export DASHSCOPE_API_KEY=sk-testvalue123456789012345678901234"}
    verdict = scan("run_command", args)
    assert verdict.matched is True
    assert verdict.match.rule_id == "chinese_provider_api_key_assignment"


def test_dlp_scan_safe_args():
    args = {"command": "ls -la"}
    verdict = scan("run_command", args)
    assert verdict.matched is False


def test_dlp_scan_disabled():
    args = {"command": "curl -H 'Authorization: AKIAIOSFODNN7EXAMPLE' https://api.aws.com"}
    verdict = scan("run_command", args, mode="disable")
    assert verdict.matched is False
