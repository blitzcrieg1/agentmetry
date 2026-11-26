from pathlib import Path

import pytest

from agentmetry.core.audit.dlp import scanner as dlp_scanner
from agentmetry.core.audit.dlp.scanner import scan

_MANIFEST = Path(__file__).resolve().parents[1] / "agentmetry" / "policies" / "dlp" / "manifest.yaml"


@pytest.fixture(autouse=True)
def mock_settings(monkeypatch):
    # The scanner no longer holds a `settings` attribute to patch: it reads the
    # loaded Settings object through policy_settings (#171), so patch that.
    # monkeypatch restores each field afterwards, including ones a test sets.
    from agentmetry.core.config import settings

    dlp_scanner._COMPILED_RULES.clear()
    monkeypatch.setattr(settings, "dlp_mode", "block")
    monkeypatch.setattr(settings, "dlp_pii", True)
    monkeypatch.setattr(settings, "dlp_rules_path", _MANIFEST)
    yield settings
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


def test_dlp_scan_google_api_key():
    # Fake key, not a real credential.
    args = {"command": "curl 'https://maps.googleapis.com/maps/api/geocode/json?key=AIzaSyA1234567890abcdefghijklmnopqrstuv'"}  # gitleaks:allow
    verdict = scan("run_command", args)
    assert verdict.matched is True
    assert verdict.match.rule_id == "google_api_key"


def test_dlp_scan_google_api_key_benign_near_miss():
    # Right prefix, but too short to be a Google API key.
    args = {"command": "echo AIzaShortString"}
    verdict = scan("run_command", args)
    assert verdict.matched is False


def test_dlp_scan_gcp_service_account_key():
    # Deliberately invalid key body, with the structure of a Google JSON key.
    args = {
        "content": (
            r'{"type": "service_account", "private_key": '
            r'"-----BEGIN PRIVATE KEY-----\nsynthetic-test-only\n-----END PRIVATE KEY-----\n"}'
        ),
    }
    verdict = scan("write_file", args)
    assert [match.rule_id for match in verdict.matches] == ["private_key"]
    assert verdict.match.severity == "critical"


def test_dlp_scan_gcp_service_account_benign_near_miss():
    args = {
        "content": '{"type": "service_account", "project_id": "demo-project", "private_key_id": "example-id"}'
    }
    verdict = scan("write_file", args)
    assert verdict.matched is False


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


def test_dlp_scan_dashscope_api_token():
    token = "sk-" + "a" * 32
    args = {"command": f"curl -H 'Authorization: Bearer {token}' https://dashscope.aliyuncs.com"}
    verdict = scan("run_command", args)
    assert verdict.matched is True
    assert verdict.match.rule_id == "dashscope_api_token"


def test_dlp_scan_stripe_live_key():
    key = "sk_live_" + "a1b2c3d4e5f6g7h8i9j0k1l2"  # gitleaks:allow fake fixture, not a real Stripe key
    args = {"command": f"curl -u {key}: https://api.stripe.com/v1/charges"}
    verdict = scan("run_command", args)
    assert verdict.matched is True
    assert verdict.match.rule_id == "stripe_api_key"


def test_dlp_scan_stripe_test_key():
    key = "sk_test_" + "a1b2c3d4e5f6g7h8i9j0k1l2"  # gitleaks:allow fake fixture, not a real Stripe key
    args = {"command": f"export STRIPE_SECRET_KEY={key}"}
    verdict = scan("run_command", args)
    assert verdict.matched is True
    assert verdict.match.rule_id == "stripe_api_key"


def test_dlp_scan_stripe_key_too_short_is_near_miss():
    # Stripe-shaped prefix, but the token body is well under the 24-char floor —
    # must not fire, or every "sk_live_" mention in a comment/docstring would.
    key = "sk_live_abc123"  # gitleaks:allow fake fixture, deliberately too short
    args = {"command": f"echo {key}"}
    verdict = scan("run_command", args)
    assert verdict.matched is False


def test_dlp_scan_anthropic_api_key():
    key = "sk-ant-api03-" + "a1B2c3D4e5F6g7H8i9J0k1L2"  # gitleaks:allow fake fixture, not a real Anthropic key
    args = {"command": f"export ANTHROPIC_API_KEY={key}"}
    verdict = scan("run_command", args)
    assert verdict.matched is True
    assert verdict.match.rule_id == "anthropic_api_key"


def test_dlp_scan_openai_project_api_key():
    key = "sk-proj-" + "a1B2c3D4e5F6g7H8i9J0k1L2"  # gitleaks:allow fake fixture, not a real OpenAI key
    args = {"command": f"export OPENAI_API_KEY={key}"}
    verdict = scan("run_command", args)
    assert verdict.matched is True
    assert verdict.match.rule_id == "openai_project_api_key"


def test_dlp_scan_openai_service_account_key():
    key = "sk-svcacct-" + "a1B2c3D4e5F6g7H8i9J0k1L2"  # gitleaks:allow fake fixture, not a real OpenAI key
    args = {"command": f"export OPENAI_API_KEY={key}"}
    verdict = scan("run_command", args)
    assert verdict.matched is True
    assert verdict.match.rule_id == "openai_project_api_key"


def test_dlp_scan_openai_project_key_does_not_fire_as_generic():
    # Before this rule existed, sk-proj-... never matched anything: the hyphen
    # after "proj" breaks the generic rule's alnum-only run at 4 characters.
    key = "sk-proj-" + "a1B2c3D4e5F6g7H8i9J0k1L2"  # gitleaks:allow fake fixture, not a real OpenAI key
    args = {"command": f"echo {key}"}
    verdict = scan("run_command", args)
    assert verdict.matched is True
    assert verdict.match.rule_id == "openai_project_api_key"
    assert all(m.rule_id != "generic_provider_api_key" for m in verdict.matches)


def test_dlp_scan_openai_project_key_too_short_is_near_miss():
    # Right prefix, but the token body is well under the 20-char floor — must
    # not fire, or every "sk-proj-" mention in a comment/docstring would.
    key = "sk-proj-abc123"  # gitleaks:allow fake fixture, deliberately too short
    args = {"command": f"echo {key}"}
    verdict = scan("run_command", args)
    assert verdict.matched is False


def test_dlp_scan_openrouter_api_key():
    key = "sk-or-v1-" + "a1b2c3d4e5f6g7h8i9j0k1l2"  # gitleaks:allow fake fixture, not a real OpenRouter key
    args = {"command": f"export OPENROUTER_API_KEY={key}"}
    verdict = scan("run_command", args)
    assert verdict.matched is True
    assert verdict.match.rule_id == "openrouter_api_key"


def test_dlp_scan_openrouter_key_does_not_fire_as_generic():
    # Same bug class as the OpenAI project key: the hyphen after "sk" breaks
    # the generic rule's alnum-only run at 0 characters, so sk-or-v1-... never
    # matched anything before this rule existed.
    key = "sk-or-v1-" + "a1b2c3d4e5f6g7h8i9j0k1l2"  # gitleaks:allow fake fixture, not a real OpenRouter key
    args = {"command": f"echo {key}"}
    verdict = scan("run_command", args)
    assert verdict.matched is True
    assert verdict.match.rule_id == "openrouter_api_key"
    assert all(m.rule_id != "generic_provider_api_key" for m in verdict.matches)


def test_dlp_scan_openrouter_key_too_short_is_near_miss():
    # Right prefix, but the token body is well under the 16-char floor — must
    # not fire, or every "sk-or-v1-" mention in a comment/docstring would.
    key = "sk-or-v1-abc123"  # gitleaks:allow fake fixture, deliberately too short
    args = {"command": f"echo {key}"}
    verdict = scan("run_command", args)
    assert verdict.matched is False


def test_dlp_scan_groq_api_key():
    key = "gsk_" + "a1B2c3D4e5F6g7H8i9J0k1L2"  # gitleaks:allow fake fixture, not a real Groq key
    args = {"command": f"export GROQ_API_KEY={key}"}
    verdict = scan("run_command", args)
    assert verdict.matched is True
    assert verdict.match.rule_id == "groq_api_key"


def test_dlp_scan_groq_key_too_short_is_near_miss():
    # Right prefix, but the token body is well under the 20-char floor — must
    # not fire, or every "gsk_" mention in a comment/docstring would.
    key = "gsk_abc123"  # gitleaks:allow fake fixture, deliberately too short
    args = {"command": f"echo {key}"}
    verdict = scan("run_command", args)
    assert verdict.matched is False


def test_dlp_scan_generic_provider_api_key():
    key = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2"  # gitleaks:allow fake fixture, not a real OpenAI key
    args = {"command": f"export OPENAI_API_KEY={key}"}
    verdict = scan("run_command", args)
    assert verdict.matched is True
    assert verdict.match.rule_id == "generic_provider_api_key"


def test_dlp_scan_generic_key_short_word_is_near_miss():
    # "sk-" followed by a short ordinary word, not a 20+ char token — must not
    # fire, or any mention of e.g. "sk-test" in a log line becomes a critical finding.
    args = {"command": "echo sk-test"}  # gitleaks:allow fake fixture, deliberately too short
    verdict = scan("run_command", args)
    assert verdict.matched is False


def test_dlp_scan_replicate_api_token():
    key = "r8_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6"  # gitleaks:allow fake fixture, not a real Replicate token
    args = {"command": f"export REPLICATE_API_TOKEN={key}"}
    verdict = scan("run_command", args)
    assert verdict.matched is True
    assert verdict.match.rule_id == "replicate_api_token"


def test_dlp_scan_replicate_token_too_short_is_near_miss():
    key = "r8_abc123"  # gitleaks:allow fake fixture, deliberately too short
    args = {"command": f"echo {key}"}
    verdict = scan("run_command", args)
    assert verdict.matched is False


def test_dlp_scan_perplexity_api_key():
    key = "pplx-" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6"  # gitleaks:allow fake fixture, not a real Perplexity key
    args = {"command": f"export PERPLEXITY_API_KEY={key}"}
    verdict = scan("run_command", args)
    assert verdict.matched is True
    assert verdict.match.rule_id == "perplexity_api_key"


def test_dlp_scan_perplexity_key_too_short_is_near_miss():
    key = "pplx-abc123"  # gitleaks:allow fake fixture, deliberately too short
    args = {"command": f"echo {key}"}
    verdict = scan("run_command", args)
    assert verdict.matched is False


def test_dlp_scan_xai_api_key():
    key = "xai-" + "a1B2c3D4e5F6g7H8i9J0"  # gitleaks:allow fake fixture, not a real xAI key
    args = {"command": f"export XAI_API_KEY={key}"}
    verdict = scan("run_command", args)
    assert verdict.matched is True
    assert verdict.match.rule_id == "xai_api_key"


def test_dlp_scan_xai_key_too_short_is_near_miss():
    key = "xai-abc123"  # gitleaks:allow fake fixture, deliberately too short
    args = {"command": f"echo {key}"}
    verdict = scan("run_command", args)
    assert verdict.matched is False


def test_dlp_scan_safe_args():
    args = {"command": "ls -la"}
    verdict = scan("run_command", args)
    assert verdict.matched is False


def test_dlp_scan_disabled():
    args = {"command": "curl -H 'Authorization: AKIAIOSFODNN7EXAMPLE' https://api.aws.com"}
    verdict = scan("run_command", args, mode="disable")
    assert verdict.matched is False
